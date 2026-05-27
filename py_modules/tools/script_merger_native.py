"""Native Linux script merger for Witcher 3 mods.

Witcher 3 mods often modify the same ``.ws`` script files (e.g. ``r4Player.ws``).
When two mods modify the same file, REDengine loads only one of them — the
other's changes are silently dropped. The official Windows tool (``Script
Merger``) solves this by 3-way-merging the conflicting scripts into a
synthetic mod (``mod0000_MergedFiles``) loaded with the highest priority.

This module does the same thing natively on Linux using GNU ``diff3``, with
conflicts auto-resolved by mods.settings ``Priority`` order. No Proton
required.

Design (modeled after ``apocalyptech/w3scriptmerge``, BSD-3, with conflict
auto-resolution layered on top):

  for each ``.ws`` file present in 2+ enabled mods:
      vanilla    = <install>/content/content0/scripts/<rel>
      running    = first mod's version (sorted by ascending Priority)
      for each later mod in priority order:
          diff3 -m running vanilla mod_version  →  text (maybe w/ conflicts)
          if text contains conflict markers:
              strip markers, keeping the higher-priority (mod) side
          running := text
      write running to <install>/Mods/mod0000_DeckyMerged/content/scripts/<rel>

Encoding: vanilla ``.ws`` files are UTF-16LE; mod files vary (UTF-16, UTF-8,
or latin1). We sniff the BOM, transcode to UTF-8 for the merge, then write
the merged output back as UTF-16LE to match the vanilla baseline.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

MERGED_MOD_NAME = "mod0000_DeckyMerged"
VANILLA_SCRIPTS_REL = Path("content") / "content0" / "scripts"


# ----------------------------------------------------------- encoding helpers


def _detect_encoding(path: Path) -> str:
    """W3 scripts are usually UTF-16LE but mod authors aren't consistent.
    BOM-sniff first, fall back to latin1 (which always decodes)."""
    with path.open("rb") as f:
        head = f.read(3)
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if head == b"\xef\xbb\xbf":
        return "utf-8-sig"
    return "latin1"


def _read_text(path: Path) -> str:
    return path.read_text(encoding=_detect_encoding(path))


def _write_utf16(path: Path, text: str) -> None:
    """Write as UTF-16LE with BOM and CRLF line endings (matches vanilla)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Newline normalization, then encode.
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    with path.open("wb") as f:
        f.write(b"\xff\xfe")  # UTF-16LE BOM
        f.write(normalized.encode("utf-16-le"))


# ------------------------------------------------------- conflict resolution


_CONFLICT_RE = re.compile(
    r"^<<<<<<< .*?\n(?P<ours>.*?)(?:^\|\|\|\|\|\|\| .*?\n(?P<base>.*?))?^=======\s*\n(?P<theirs>.*?)^>>>>>>> .*?\n",
    re.MULTILINE | re.DOTALL,
)


def _resolve_conflicts_pick_later(text: str) -> str:
    """Strip diff3 ``-m`` conflict markers, keeping the LATER (higher-priority)
    side. Callers pass mods in ascending priority order, so the ``theirs`` side
    of each diff3 invocation is always the higher-priority candidate.

    ``diff3 -m`` block format:

        <<<<<<< /path/to/running
        lines from the running merge
        ||||||| /path/to/vanilla
        lines from vanilla   (optional — only present in 3-way merges)
        =======
        lines from the new mod    ← KEEP
        >>>>>>> /path/to/mod
    """
    return _CONFLICT_RE.sub(lambda m: m.group("theirs"), text)


# --------------------------------------------------------------- discovery


def _iter_ws_files(mod_root: Path) -> Iterable[Path]:
    """Every ``.ws`` file inside a single mod's ``content/scripts/`` tree."""
    scripts = mod_root / "content" / "scripts"
    if not scripts.is_dir():
        return
    for p in scripts.rglob("*.ws"):
        if p.is_file() or p.is_symlink():
            yield p


def _script_rel(mod_root: Path, script: Path) -> Path:
    """``content/scripts/game/player/r4Player.ws`` form, mod-root-relative."""
    return script.relative_to(mod_root)


# ----------------------------------------------------------------- merging


def _read_priorities(mods_settings_path: Path) -> dict[str, int]:
    """Parse mods.settings → {folder_name: priority}. Missing entries get a
    big number so they sort last (and thus win conflicts by default)."""
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


def _diff3_merge(running: str, vanilla: str, mod: str, tmpdir: Path) -> str:
    """Run ``diff3 -m`` and return its output (may contain conflict markers)."""
    p_running = tmpdir / "running"
    p_vanilla = tmpdir / "vanilla"
    p_mod = tmpdir / "mod"
    p_running.write_text(running, encoding="utf-8")
    p_vanilla.write_text(vanilla, encoding="utf-8")
    p_mod.write_text(mod, encoding="utf-8")
    cp = subprocess.run(
        ["diff3", "-m", str(p_running), str(p_vanilla), str(p_mod)],
        capture_output=True, encoding="utf-8",
    )
    # diff3 returns 0 (no conflict) or 1 (conflicts) — both produce useful stdout.
    # >1 is a real error.
    if cp.returncode > 1:
        raise RuntimeError(f"diff3 failed (rc={cp.returncode}): {cp.stderr}")
    return cp.stdout


def _do_merge(
    install: Path,
    mods: list[dict],
    mods_settings_path: Path,
) -> dict:
    """Synchronous merge core. ``mods`` is the list of enabled mods as dicts
    with at least ``id`` (folder name) and ``files`` (relative paths)."""

    if shutil.which("diff3") is None:
        raise RuntimeError("GNU diff3 not found on PATH (install diffutils)")

    priorities = _read_priorities(mods_settings_path)

    # Group .ws files by relative path → [(priority, mod_root)]
    by_rel: dict[Path, list[tuple[int, Path]]] = defaultdict(list)
    for mod in mods:
        mod_name = mod["folder"]
        mod_root = install / "Mods" / mod_name
        if not mod_root.is_dir():
            continue
        prio = priorities.get(mod_name, 99999)
        for script in _iter_ws_files(mod_root):
            rel = _script_rel(mod_root, script)
            by_rel[rel].append((prio, mod_root))

    vanilla_root = install / VANILLA_SCRIPTS_REL.parent  # …/content/content0
    merged_root = install / "Mods" / MERGED_MOD_NAME
    # Wipe the previous merged mod so stale files don't linger.
    if merged_root.exists():
        shutil.rmtree(merged_root)

    merged_files: list[str] = []
    conflicts_auto_resolved: list[str] = []
    skipped_no_vanilla: list[str] = []

    with tempfile.TemporaryDirectory(prefix="w3merge-") as td:
        tmpdir = Path(td)
        for rel, entries in sorted(by_rel.items()):
            if len(entries) < 2:
                continue  # nothing to merge — engine already loads it fine

            entries.sort(key=lambda t: t[0])  # ascending priority
            vanilla_path = install / rel  # rel is "content/scripts/foo.ws"
            # The vanilla baseline lives under content/content0/, not content/.
            vanilla_path = vanilla_root / Path(*rel.parts[1:])  # strip "content/"
            if not vanilla_path.exists():
                skipped_no_vanilla.append(str(rel))
                continue
            vanilla_text = _read_text(vanilla_path)

            running = _read_text(entries[0][1] / rel)
            had_conflict = False
            for _prio, mod_root in entries[1:]:
                mod_text = _read_text(mod_root / rel)
                merged = _diff3_merge(running, vanilla_text, mod_text, tmpdir)
                if "<<<<<<<" in merged:
                    merged = _resolve_conflicts_pick_later(merged)
                    had_conflict = True
                running = merged

            out_path = merged_root / rel
            _write_utf16(out_path, running)
            merged_files.append(str(rel))
            if had_conflict:
                conflicts_auto_resolved.append(str(rel))

    return {
        "merged_mod_name": MERGED_MOD_NAME,
        "merged_files": merged_files,
        "conflicts_auto_resolved": conflicts_auto_resolved,
        "skipped_no_vanilla": skipped_no_vanilla,
        "output_dir": str(merged_root),
    }


async def native_merge(
    install: Path,
    *,
    mods: list[dict],
    mods_settings_path: Path,
) -> dict:
    """Async wrapper so the Decky event loop isn't blocked by diff3."""
    return await asyncio.to_thread(_do_merge, install, mods, mods_settings_path)
