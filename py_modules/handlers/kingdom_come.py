"""Kingdom Come: Deliverance (and KCD2) handler.

Layout the game expects (per modding.wiki + Nexus KCD modding guide):

* Each mod is a folder under ``<install>/Mods/<mod_name>/``
* Inside a mod folder:
    ``mod.manifest``  — optional XML metadata
    ``mod.cfg``       — optional config
    ``Data/*.pak``    — the actual content
    ``Localization/*.pak`` — string files
* Load order / enable-list lives in ``<install>/Mods/mod_order.txt``

mod_order.txt semantics (load-bearing, often misunderstood):

* If the file is **absent**, mods load in alphabetical order — all of them.
* If the file is **present**, it acts as a **whitelist** AND an order spec:
  only mods listed (one folder name per line) load, in that order.
* Lines starting with ``#`` are comments (you can disable a mod by
  commenting out its line).

Our behaviour:

* On enable, append the mod's folder name to mod_order.txt **only if the
  file already exists** — otherwise we let alphabetical default do its job.
  This avoids silently demoting existing mods to "not loaded" by creating
  a partial whitelist on the user's behalf.
* On disable, remove the mod's folder name from mod_order.txt if present.

Unlike Witcher 3, KCD has no ``mod`` folder prefix requirement, and the
mod_order.txt lives inside the install (not the Proton prefix Documents).

Steam appids:
  379430  — Kingdom Come: Deliverance
  1771300 — Kingdom Come: Deliverance II  (same layout, same handler)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from handlers.base import (
    BaseHandler,
    EnableResult,
    GameLike,
    flatten_single_root,
    restore_tree,
    symlink_tree,
)

KCD_APPID = "379430"
KCD2_APPID = "1771300"


# Files/dirs that indicate "this is a KCD mod's content tree" — used when
# detecting how an archive is shaped.
_MOD_INNER_MARKERS = {"data", "localization", "mod.manifest", "mod.cfg"}


def _looks_like_kcd_mod(p: Path) -> bool:
    """True if ``p`` is a folder containing the inside of a single KCD mod."""
    return p.is_dir() and any(c.name.lower() in _MOD_INNER_MARKERS for c in p.iterdir())


def _has_mods_dir(p: Path) -> bool:
    return (p / "Mods").is_dir() or (p / "mods").is_dir()


class KingdomComeHandler(BaseHandler):
    name = "kingdom_come"
    games = {KCD_APPID: "kingdomcomedeliverance", KCD2_APPID: "kingdomcomedeliverance2"}

    # ------------------------------------------------------------ payload

    def post_install_payload(self, payload_root: Path, game_root: Path | None = None) -> None:
        """Normalize the extracted archive to the KCD install-relative layout.

        After this runs, ``payload_root`` should look like a chunk of the
        game install: ``Mods/<modname>/Data/...`` etc.

        Common archive shapes (in priority order):

        A. ``Mods/MyMod/Data/...``  — already wrapped, leave alone
        B. ``MyMod/Data/...``       — single mod folder, wrap into ``Mods/``
        C. ``Data/...`` (or ``mod.manifest``, etc) — bare mod contents,
           wrap into ``Mods/mod<uuid>/``
        D. ``WrapperDir/<one of the above>`` — hoist the wrapper first
        """
        # 1) Hoist single-wrapper dirs (e.g. an archive nested inside
        # "ModName-Vortex/" or similar). Stop if the inner dir is itself
        # meaningful — a mod folder, the install-root, or a payload marker.
        for _ in range(5):
            entries = [e for e in payload_root.iterdir() if not e.name.startswith(".")]
            if len(entries) != 1 or not entries[0].is_dir():
                break
            inner = entries[0]
            if _has_mods_dir(inner) or _looks_like_kcd_mod(inner):
                if _has_mods_dir(inner):
                    flatten_single_root(payload_root)
                break
            # Inner is a generic wrapper folder — hoist its contents up.
            flatten_single_root(payload_root)

        # 2) Already at install-root layout? Done.
        if _has_mods_dir(payload_root):
            return

        entries = [e for e in payload_root.iterdir() if not e.name.startswith(".")]

        # 3) A bunch of single-mod folders at the root — wrap into Mods/
        mod_folders = [e for e in entries if _looks_like_kcd_mod(e)]
        if mod_folders:
            mods_dir = payload_root / "Mods"
            mods_dir.mkdir(exist_ok=True)
            for mf in mod_folders:
                target = mods_dir / mf.name
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(mf), str(target))
            return

        # 4) Bare mod contents (Data/, Localization/, mod.manifest) at the
        # root — wrap the whole payload into Mods/mod<uuid>/.
        wrapper = payload_root / "Mods" / payload_root.name
        wrapper.mkdir(parents=True, exist_ok=True)
        for child in list(payload_root.iterdir()):
            if child.name in {"Mods", "mods"}:
                continue
            shutil.move(str(child), str(wrapper / child.name))

    # ----------------------------------------------------------- enable

    def enable(self, game: GameLike, payload_root: Path, backup_root: Path) -> EnableResult:
        game_root = Path(game.install_path)
        if not game_root.exists():
            raise FileNotFoundError(f"game install path missing: {game_root}")
        backup_root.mkdir(parents=True, exist_ok=True)

        files = symlink_tree(payload_root, game_root, backup_root)

        mod_names = sorted({
            Path(rel).parts[1]
            for rel in files
            if len(Path(rel).parts) >= 2 and Path(rel).parts[0] in ("Mods", "mods")
        })
        if mod_names:
            _ensure_mod_order_entries(game_root / "Mods" / "mod_order.txt", mod_names)

        return EnableResult(files=files)

    # ----------------------------------------------------------- disable

    def disable(self, game: GameLike, files: list[str], backup_root: Path) -> None:
        game_root = Path(game.install_path)
        mod_names = sorted({
            Path(rel).parts[1]
            for rel in files
            if len(Path(rel).parts) >= 2 and Path(rel).parts[0] in ("Mods", "mods")
        })
        if mod_names:
            _remove_mod_order_entries(game_root / "Mods" / "mod_order.txt", mod_names)

        restore_tree(game_root, files, backup_root)


# ---------------------------------------------------------- mod_order.txt io


def _read_mod_order(path: Path) -> list[str]:
    """Return mod_order.txt's effective entries (commented/blank lines kept
    for round-tripping). For decision logic, callers should check
    ``startswith("#")`` and ``.strip()``.
    """
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _write_mod_order(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(path)


def _active_entries(lines: list[str]) -> set[str]:
    """Folder names that mod_order.txt currently activates (uncommented)."""
    out: set[str] = set()
    for line in lines:
        s = line.split("#", 1)[0].strip()
        if s:
            out.add(s)
    return out


def _ensure_mod_order_entries(path: Path, mod_names: list[str]) -> None:
    """Append ``mod_names`` to mod_order.txt **only if the file already
    exists**. Creating a partial mod_order.txt on the user's behalf would
    accidentally turn the alphabetical default into a whitelist that
    excludes their other mods.
    """
    if not path.exists():
        return
    lines = _read_mod_order(path)
    active = _active_entries(lines)
    appended = False
    for name in mod_names:
        if name not in active:
            lines.append(name)
            active.add(name)
            appended = True
    if appended:
        _write_mod_order(path, lines)


def _remove_mod_order_entries(path: Path, mod_names: list[str]) -> None:
    if not path.exists():
        return
    targets = set(mod_names)
    lines = _read_mod_order(path)
    kept = [
        line for line in lines
        if line.split("#", 1)[0].strip() not in targets
    ]
    if kept != lines:
        _write_mod_order(path, kept)
