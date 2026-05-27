"""Witcher 3 handler.

Layout the game actually expects (see sinitar/CDPR REDkit modding guides):

* Content mods:         ``<install>/Mods/<modname>/content/...``
* DLCs:                 ``<install>/DLC/<dlcname>/content/...``
* Load order / enable:  ``<userdata>/Documents/The Witcher 3/mods.settings``
                        (INI: section per mod, ``Enabled`` / ``Priority`` keys)

Under Proton on Linux/Steam Deck, ``<userdata>`` lives inside the prefix:
    <library>/steamapps/compatdata/292030/pfx/drive_c/users/steamuser/

Important rules we enforce:
- Mod folders inside ``Mods/`` MUST start with the literal prefix ``mod`` or
  the engine ignores them. We rename if needed.
- mods.settings must be in the prefix's Documents dir, NOT in the install root.
  (Writing it under ``<install>/Mods/`` is a no-op — the game never reads it.)
- The most common archive shape is ``modFooBar/content/scripts/...`` at the
  archive root. We wrap that into ``Mods/modFooBar/`` WITHOUT duplicating the
  ``content/`` segment.
"""

from __future__ import annotations

import configparser
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

WITCHER3_APPID = "292030"  # The Witcher 3: Wild Hunt on Steam


# --------------------------------------------------------------- layout helpers


def _real_entries(p: Path) -> list[Path]:
    return [e for e in p.iterdir() if not e.name.startswith(".")]


def _has_install_root_layout(p: Path) -> bool:
    """The dir looks like a partial game install: a ``Mods/`` or ``DLC/`` at top."""
    for name in ("Mods", "DLC", "mods", "dlc"):
        if (p / name).is_dir():
            return True
    return False


def _is_mod_folder(p: Path) -> bool:
    """A directory that on its own represents one mod (has content/ inside)."""
    return p.is_dir() and (p / "content").is_dir()


def _is_dlc_folder(p: Path) -> bool:
    return p.is_dir() and p.name.lower().startswith("dlc") and (p / "content").is_dir()


# Meaningful W3 path segments we must NOT hoist away — they're load-bearing.
_RESERVED_NAMES = {"content", "bin", "scripts", "dlc", "mods"}


def _is_meaningful_segment(p: Path) -> bool:
    """True if hoisting this dir would lose information the game needs."""
    name = p.name.lower()
    return (
        name in _RESERVED_NAMES
        or name.startswith("mod")
        or name.startswith("dlc")
    )


def _ensure_mod_prefix(name: str) -> str:
    return name if name.lower().startswith("mod") else f"mod{name}"


def _normalize_mods_dir(mods_dir: Path) -> None:
    """Rename any ``Mods/X/`` whose name doesn't start with ``mod`` to ``modX``.

    REDengine silently skips folders without the prefix, so this is load-bearing.
    """
    if not mods_dir.is_dir():
        return
    for entry in list(mods_dir.iterdir()):
        if entry.is_dir() and not entry.name.lower().startswith("mod"):
            new = mods_dir / _ensure_mod_prefix(entry.name)
            if not new.exists():
                entry.rename(new)


# ---------------------------------------------------------- proton prefix paths


def _w3_documents_dir(install_path: Path, appid: str) -> Path | None:
    """Locate the Proton prefix's ``Documents/The Witcher 3`` dir.

    ``install_path`` is ``<library>/steamapps/common/The Witcher 3``, so the
    sibling ``compatdata/<appid>/pfx/drive_c/users/steamuser/Documents/...`` is
    where Wine maps the user's My Documents folder.
    Returns ``None`` if no Proton prefix exists for this game.
    """
    steamapps = install_path.parent.parent
    if steamapps.name != "steamapps" or not steamapps.is_dir():
        return None
    prefix = steamapps / "compatdata" / appid / "pfx"
    if not prefix.is_dir():
        return None
    return prefix / "drive_c" / "users" / "steamuser" / "Documents" / "The Witcher 3"


def _mods_settings_path(install_path: Path, appid: str) -> Path:
    """Where mods.settings goes. Prefer the prefix's Documents dir; fall back
    to the install ``Mods/`` only if no prefix exists (so we don't lose state
    entirely on an unusual setup)."""
    docs = _w3_documents_dir(install_path, appid)
    if docs is not None:
        return docs / "mods.settings"
    return install_path / "Mods" / "mods.settings"


# -------------------------------------------------------------------- handler


class Witcher3Handler(BaseHandler):
    name = "witcher3"

    # ------------------------------------------------------------ payload

    def post_install_payload(self, payload_root: Path) -> None:
        """Normalize the extracted archive to the W3 install-root layout.

        After this runs, ``payload_root`` should look like a chunk of the
        game install: ``Mods/modX/content/...`` and/or ``DLC/dlcY/...``.
        ``symlink_tree`` then mirrors it straight into the game directory.
        """
        # 1) Hoist single-wrapper dirs (e.g. an archive that nests everything
        # inside ``MyMod-v2.1/``) until we're at the meaningful root. NEVER
        # hoist a meaningful segment (``content/``, ``scripts/``, a ``modX/``
        # folder, etc.) — those carry information the game needs.
        for _ in range(5):
            entries = _real_entries(payload_root)
            if len(entries) != 1 or not entries[0].is_dir():
                break
            inner = entries[0]
            if _has_install_root_layout(inner):
                # The wrapper hides an actual install-root layout; hoist
                # exactly once to reveal it, then break.
                flatten_single_root(payload_root)
                break
            # Stop if the single inner IS itself the mod we want to keep
            # (whether it's named modX or has a content/ tree inside).
            if (
                _is_meaningful_segment(inner)
                or _is_mod_folder(inner)
                or _is_dlc_folder(inner)
            ):
                break
            flatten_single_root(payload_root)

        # 2) Already at install-root layout? Just enforce mod-folder naming.
        if _has_install_root_layout(payload_root):
            _normalize_mods_dir(payload_root / "Mods")
            _normalize_mods_dir(payload_root / "mods")
            return

        entries = _real_entries(payload_root)

        # 3) A bunch of modX/ (or dlcY/) folders at the root — wrap into Mods/DLC.
        mod_folders = [e for e in entries if _is_mod_folder(e) and not _is_dlc_folder(e)]
        dlc_folders = [e for e in entries if _is_dlc_folder(e)]
        if mod_folders or dlc_folders:
            if mod_folders:
                mods_dir = payload_root / "Mods"
                mods_dir.mkdir(exist_ok=True)
                for mf in mod_folders:
                    target = mods_dir / _ensure_mod_prefix(mf.name)
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.move(str(mf), str(target))
            if dlc_folders:
                dlc_dir = payload_root / "DLC"
                dlc_dir.mkdir(exist_ok=True)
                for df in dlc_folders:
                    target = dlc_dir / df.name
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.move(str(df), str(target))
            return

        # 4) Bare ``content/`` (or just ``scripts/``, ``bin/``…) at the root —
        # treat the whole payload as a single mod's contents and wrap it.
        wrapper = payload_root / "Mods" / f"mod{payload_root.name}"
        wrapper.mkdir(parents=True, exist_ok=True)
        for child in list(payload_root.iterdir()):
            if child.name in {"Mods", "DLC", "mods", "dlc"}:
                continue
            shutil.move(str(child), str(wrapper / child.name))

    # ----------------------------------------------------------- enable

    def enable(self, game: GameLike, payload_root: Path, backup_root: Path) -> EnableResult:
        game_root = Path(game.install_path)
        if not game_root.exists():
            raise FileNotFoundError(f"game install path missing: {game_root}")
        backup_root.mkdir(parents=True, exist_ok=True)

        files = symlink_tree(payload_root, game_root, backup_root)

        # Pick up every mod folder we just linked under Mods/.
        mod_names = sorted({
            Path(rel).parts[1]
            for rel in files
            if len(Path(rel).parts) >= 2 and Path(rel).parts[0] in ("Mods", "mods")
        })
        if mod_names:
            settings_path = _mods_settings_path(game_root, game.id)
            _ensure_mods_settings_entries(settings_path, mod_names, enabled=True)

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
            _remove_mods_settings_entries(_mods_settings_path(game_root, game.id), mod_names)

        restore_tree(game_root, files, backup_root)

    # ----------------------------------------------------------- tools

    def tools(self) -> list[dict]:
        return [
            {
                "id": "script_merger_status",
                "label": "Script Merger (Proton GUI)",
                "description": "Detect, install, and launch the Windows Script Merger under Proton.",
            },
            {
                "id": "script_merger_native",
                "label": "Script Merger (native Linux)",
                "description": "Merge .ws scripts from enabled mods using GNU diff3 — no Proton required.",
            },
            {
                "id": "settings_merger_native",
                "label": "Settings Merger (native Linux)",
                "description": "Merge input.xml / userConfigDef.xml from enabled mods using GNU diff3.",
            },
            {
                "id": "remove_merged",
                "label": "Remove merged outputs",
                "description": "Delete Mods/mod0000_DeckyMerged and restore baseline settings.",
            },
            {
                "id": "mods_settings_path",
                "label": "Show mods.settings path",
                "description": "Show the resolved on-disk path the handler is writing to.",
            },
        ]

    async def run_tool(self, tool_id: str, game: GameLike, **kwargs) -> dict:
        install = Path(game.install_path)
        if tool_id == "script_merger_status":
            from tools.script_merger import script_merger_action
            return await script_merger_action(
                kwargs.get("action", "status"),
                install,
                api_key=kwargs.get("api_key"),
            )
        if tool_id == "script_merger_native":
            from tools.script_merger_native import native_merge
            return await native_merge(
                install,
                mods=kwargs.get("mods", []),
                mods_settings_path=_mods_settings_path(install, game.id),
            )
        if tool_id == "settings_merger_native":
            from tools.settings_merger_native import native_settings_merge
            data_dir = kwargs.get("data_dir")
            if data_dir is None:
                raise ValueError("settings_merger_native requires data_dir")
            return await native_settings_merge(
                install,
                data_dir=Path(data_dir),
                game_id=game.id,
                mods=kwargs.get("mods", []),
                mods_settings_path=_mods_settings_path(install, game.id),
            )
        if tool_id == "remove_merged":
            from tools.settings_merger_native import restore_settings_baselines
            data_dir = kwargs.get("data_dir")
            removed_script = False
            merged_dir = install / "Mods" / "mod0000_DeckyMerged"
            if merged_dir.exists():
                import shutil as _sh
                _sh.rmtree(merged_dir)
                removed_script = True
            restored = {"restored": [], "cleared_baseline_dir": False}
            if data_dir is not None:
                restored = await restore_settings_baselines(
                    install, data_dir=Path(data_dir), game_id=game.id,
                )
            return {
                "removed_merged_script_mod": removed_script,
                "restored_settings_files": restored["restored"],
            }
        if tool_id == "mods_settings_path":
            p = _mods_settings_path(install, game.id)
            return {
                "path": str(p),
                "exists": p.exists(),
                "using_prefix_documents": _w3_documents_dir(install, game.id) is not None,
            }
        return await super().run_tool(tool_id, game, **kwargs)


# ---------------------------------------------------------- mods.settings io


def _read_mods_settings(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.optionxform = str  # preserve case
    if path.exists():
        try:
            cp.read(path, encoding="utf-8-sig")
        except (configparser.Error, OSError):
            pass
    return cp


def _write_mods_settings(path: Path, cp: configparser.ConfigParser) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        cp.write(f, space_around_delimiters=False)
    tmp.replace(path)


def _ensure_mods_settings_entries(path: Path, mod_names: list[str], *, enabled: bool) -> None:
    cp = _read_mods_settings(path)
    next_priority = max(
        (int(cp[s].get("Priority", "0")) for s in cp.sections() if cp[s].get("Priority", "").isdigit()),
        default=-1,
    ) + 1
    for name in mod_names:
        if not cp.has_section(name):
            cp.add_section(name)
            cp.set(name, "Enabled", "1" if enabled else "0")
            cp.set(name, "Priority", str(next_priority))
            next_priority += 1
        else:
            cp.set(name, "Enabled", "1" if enabled else "0")
    _write_mods_settings(path, cp)


def _remove_mods_settings_entries(path: Path, mod_names: list[str]) -> None:
    if not path.exists():
        return
    cp = _read_mods_settings(path)
    for name in mod_names:
        if cp.has_section(name):
            cp.remove_section(name)
    _write_mods_settings(path, cp)
