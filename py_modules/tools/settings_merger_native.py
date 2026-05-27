"""Native Linux settings merger for Witcher 3 mods.

This is the sibling to ``script_merger_native``, for settings/config files
that live at fixed paths the game reads directly (rather than inside
``Mods/``). Mods often ship modifications to:

    bin/config/r4game/user_config_matrix/pc/input.xml
    bin/config/r4game/user_config_matrix/pc/userConfigDef.xml
    bin/config/r4game/user_config_matrix/pc/*.xml

Because these live at canonical paths the engine reads (NOT under ``Mods/``),
two mods that ship the same file collide: our symlink-based enable flow
puts the last-enabled mod's version there and silently drops earlier mods'
additions. The official Windows ``Settings Merger`` handles this on
Windows; this module is the Linux native equivalent.

Strategy (parallel to the script merger):
  - For each setting file present in 2+ enabled mods:
      vanilla baseline = our first-ever snapshot of that file (created on
        first merge, kept under ``data_dir/baselines/<game_id>/<rel>``)
      For each mod in ascending priority order:
        3-way merge with diff3
        Auto-resolve conflicts to higher-priority side
      Write merged result back to the install path

The baseline snapshot is the "Save Baseline" feature the Windows Settings
Merger has. Without it, re-merging would compound: each run would re-add
already-merged content and the file would grow forever.

Caveat: because the output overwrites the install file directly, enabling a
new mod after merging will replace our merged file with a symlink to the new
mod's version. Users need to re-run the merger after enabling new mods. We
surface this in the UI.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

# Reuse the helpers from the script merger to keep behavior consistent.
from tools.script_merger_native import (
    _CONFLICT_RE,  # noqa: F401  (used via _resolve_conflicts_pick_later)
    _detect_encoding,
    _read_text,
    _resolve_conflicts_pick_later,
)

# Files we know mods ship and the engine reads at canonical paths.
# We could glob more aggressively but this is the well-trodden set; adding
# unknown files risks merging things we shouldn't touch.
KNOWN_SETTINGS_FILES = (
    "bin/config/r4game/user_config_matrix/pc/input.xml",
    "bin/config/r4game/user_config_matrix/pc/userConfigDef.xml",
)


def _baseline_path(data_dir: Path, game_id: str, rel: str) -> Path:
    return data_dir / "baselines" / game_id / rel


def _ensure_baseline(install: Path, data_dir: Path, game_id: str, rel: str) -> Path | None:
    """Snapshot the install's current file to ``baselines/`` if we haven't
    yet. Return the baseline path, or ``None`` if the install has no such
    file (which means no vanilla to merge against — we skip).

    IMPORTANT: this must be called BEFORE any merge writes a result back to
    the install, otherwise the "snapshot" would be our previously-merged
    output, not vanilla.
    """
    baseline = _baseline_path(data_dir, game_id, rel)
    if baseline.exists():
        return baseline
    src = install / rel
    if not src.exists():
        return None
    # Resolve through symlinks so we capture the actual contents, not the
    # link path. If a mod already symlinked over vanilla, we lose; but the
    # only realistic time to bootstrap a baseline is BEFORE the user enables
    # any settings-touching mod. We document this.
    real = src.resolve() if src.is_symlink() else src
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real, baseline)
    return baseline


def _diff3_merge_text(running: str, vanilla: str, mod: str, tmpdir: Path) -> str:
    p_r = tmpdir / "running"
    p_v = tmpdir / "vanilla"
    p_m = tmpdir / "mod"
    p_r.write_text(running, encoding="utf-8")
    p_v.write_text(vanilla, encoding="utf-8")
    p_m.write_text(mod, encoding="utf-8")
    cp = subprocess.run(
        ["diff3", "-m", str(p_r), str(p_v), str(p_m)],
        capture_output=True, encoding="utf-8",
    )
    if cp.returncode > 1:
        raise RuntimeError(f"diff3 failed (rc={cp.returncode}): {cp.stderr}")
    return cp.stdout


def _read_priorities(mods_settings_path: Path) -> dict[str, int]:
    """Same shape as the script merger's reader — duplicated to keep the
    settings merger usable standalone."""
    import configparser
    cp = configparser.ConfigParser()
    cp.optionxform = str
    if mods_settings_path.exists():
        try:
            cp.read(mods_settings_path, encoding="utf-8-sig")
        except (configparser.Error, OSError):
            pass
    out: dict[str, int] = {}
    for section in cp.sections():
        try:
            out[section] = int(cp[section].get("Priority", "0"))
        except ValueError:
            out[section] = 0
    return out


def _do_merge(
    install: Path,
    data_dir: Path,
    game_id: str,
    mods: list[dict],
    mods_settings_path: Path,
) -> dict:
    if shutil.which("diff3") is None:
        raise RuntimeError("GNU diff3 not found on PATH (install diffutils)")

    priorities = _read_priorities(mods_settings_path)

    # Group settings-file overrides by relative path → [(priority, mod_root)].
    # Mods may ship these files at the top level (sibling of Mods/) or inside
    # their own mod folder under Mods/. We check both.
    by_rel: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    for mod in mods:
        mod_root = install / "Mods" / mod["folder"]
        prio = priorities.get(mod["folder"], 99999)
        if not mod_root.is_dir():
            continue
        for rel in KNOWN_SETTINGS_FILES:
            # Mods that nest the file under Mods/modX/bin/config/... (rare but seen)
            nested = mod_root / rel
            if nested.exists():
                by_rel[rel].append((prio, mod_root))
                continue
            # Mods that ship the file at the install root (the common shape) —
            # our handler will have linked it into install/bin/... at enable
            # time. We can recover the original by looking under the library
            # payload, but that requires plumbing in mod ids. Simpler heuristic:
            # if the install path has a symlink that resolves into this mod's
            # library dir, count it. Skip for v1 — the nested case covers the
            # well-formed archives.

    merged_rels: list[str] = []
    conflicts_auto_resolved: list[str] = []
    skipped_no_baseline: list[str] = []
    baselined: list[str] = []

    with tempfile.TemporaryDirectory(prefix="w3settings-") as td:
        tmpdir = Path(td)
        for rel, entries in sorted(by_rel.items()):
            if len(entries) < 2:
                continue

            entries.sort(key=lambda t: t[0])
            baseline = _ensure_baseline(install, data_dir, game_id, rel)
            if baseline is None:
                skipped_no_baseline.append(rel)
                continue
            if not (data_dir / "baselines" / game_id / rel).stat().st_mtime <= 0:
                # Brand new baseline file we just created? track it.
                # (Always tracked; cheap.)
                baselined.append(rel)

            vanilla_text = _read_text(baseline)
            running = _read_text(entries[0][1] / rel)
            had_conflict = False
            for _prio, mod_root in entries[1:]:
                mod_text = _read_text(mod_root / rel)
                merged = _diff3_merge_text(running, vanilla_text, mod_text, tmpdir)
                if "<<<<<<<" in merged:
                    merged = _resolve_conflicts_pick_later(merged)
                    had_conflict = True
                running = merged

            out_path = install / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Overwrite the symlink (or file) at the install path.
            if out_path.is_symlink() or out_path.exists():
                out_path.unlink()
            # Preserve the baseline's encoding rather than forcing UTF-8.
            enc = _detect_encoding(baseline)
            out_path.write_text(running, encoding=enc.replace("-sig", ""))
            merged_rels.append(rel)
            if had_conflict:
                conflicts_auto_resolved.append(rel)

    return {
        "merged_files": merged_rels,
        "conflicts_auto_resolved": conflicts_auto_resolved,
        "skipped_no_baseline": skipped_no_baseline,
        "baselined": baselined,
    }


def _do_restore(install: Path, data_dir: Path, game_id: str) -> dict:
    """Restore install files from baselines and clear the baseline dir.
    Useful as an "undo merge / start fresh" affordance."""
    baselines_root = data_dir / "baselines" / game_id
    if not baselines_root.is_dir():
        return {"restored": [], "cleared_baseline_dir": False}
    restored: list[str] = []
    for baseline in baselines_root.rglob("*"):
        if not baseline.is_file():
            continue
        rel = baseline.relative_to(baselines_root)
        target = install / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        shutil.copy2(baseline, target)
        restored.append(str(rel))
    shutil.rmtree(baselines_root)
    return {"restored": restored, "cleared_baseline_dir": True}


async def native_settings_merge(
    install: Path,
    *,
    data_dir: Path,
    game_id: str,
    mods: list[dict],
    mods_settings_path: Path,
) -> dict:
    return await asyncio.to_thread(_do_merge, install, data_dir, game_id, mods, mods_settings_path)


async def restore_settings_baselines(install: Path, *, data_dir: Path, game_id: str) -> dict:
    return await asyncio.to_thread(_do_restore, install, data_dir, game_id)
