"""Witcher 3 handler.

Witcher 3 mods follow a specific layout:

* Content mods extract to ``<install>/Mods/<modname>/content/...``
* DLCs go to ``<install>/DLC/<dlcname>/...``
* Load order / enabled state lives in ``<install>/Mods/mods.settings``
  (a simple INI: one section per mod, with ``Enabled`` / ``Priority`` keys)

If the mod archive already follows the W3 layout (top-level ``Mods/`` and/or
``DLC/`` directories), we mirror it as-is. Otherwise we wrap the payload in
``Mods/<modname>/content/`` to match the expected structure.
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
    iter_files,
    restore_tree,
    symlink_tree,
)

WITCHER3_APPID = "292030"  # The Witcher 3: Wild Hunt on Steam


def _looks_like_w3_layout(root: Path) -> bool:
    return (root / "Mods").is_dir() or (root / "DLC").is_dir()


class Witcher3Handler(BaseHandler):
    name = "witcher3"

    # ------------------------------------------------------------ payload

    def post_install_payload(self, payload_root: Path) -> None:
        """Normalize the extracted payload to the W3 layout.

        Detection precedence:
        1. If the payload already has Mods/ or DLC/ at the root, leave it alone.
        2. If a single top-level dir wraps a W3 layout, flatten just that.
        3. Otherwise treat the whole payload as a mod's content/ tree and
           wrap it in Mods/mod<uuid>/content/ so W3 can find it.
        """
        if _looks_like_w3_layout(payload_root):
            return
        entries = [p for p in payload_root.iterdir() if not p.name.startswith(".")]
        if len(entries) == 1 and entries[0].is_dir() and _looks_like_w3_layout(entries[0]):
            flatten_single_root(payload_root)
            return
        flatten_single_root(payload_root)
        if _looks_like_w3_layout(payload_root):
            return
        wrapper = payload_root / "Mods" / f"mod{payload_root.name}" / "content"
        wrapper.mkdir(parents=True, exist_ok=True)
        for child in list(payload_root.iterdir()):
            if child.name == "Mods":
                continue
            shutil.move(str(child), str(wrapper / child.name))

    # ----------------------------------------------------------- enable

    def enable(self, game: GameLike, payload_root: Path, backup_root: Path) -> EnableResult:
        game_root = Path(game.install_path)
        if not game_root.exists():
            raise FileNotFoundError(f"game install path missing: {game_root}")
        backup_root.mkdir(parents=True, exist_ok=True)

        # Link the payload tree into the game dir (uses the same mirror logic
        # as the generic handler — backups are still recorded for any vanilla
        # files we'd overwrite, though that's rare for W3 mods).
        files = symlink_tree(payload_root, game_root, backup_root)

        # Update mods.settings for every Mods/<modname>/ we just linked in.
        mod_names = sorted({
            Path(rel).parts[1]
            for rel in files
            if Path(rel).parts[:1] == ("Mods",) and len(Path(rel).parts) >= 2
        })
        if mod_names:
            _ensure_mods_settings_entries(game_root / "Mods" / "mods.settings", mod_names, enabled=True)

        return EnableResult(files=files)

    # ----------------------------------------------------------- disable

    def disable(self, game: GameLike, files: list[str], backup_root: Path) -> None:
        game_root = Path(game.install_path)
        # Remove from mods.settings before tearing down the dirs.
        mod_names = sorted({
            Path(rel).parts[1]
            for rel in files
            if Path(rel).parts[:1] == ("Mods",) and len(Path(rel).parts) >= 2
        })
        if mod_names:
            _remove_mods_settings_entries(game_root / "Mods" / "mods.settings", mod_names)

        restore_tree(game_root, files, backup_root)

    # ----------------------------------------------------------- tools

    def tools(self) -> list[dict]:
        return [
            {
                "id": "script_merger_status",
                "label": "Script Merger",
                "description": "Detect, install, and launch the Witcher 3 Script Merger.",
            }
        ]

    async def run_tool(self, tool_id: str, game: GameLike, **kwargs) -> dict:
        from tools.script_merger import script_merger_action

        if tool_id == "script_merger_status":
            return await script_merger_action(
                kwargs.get("action", "status"),
                Path(game.install_path),
                api_key=kwargs.get("api_key"),
            )
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
    tmp = path.with_suffix(".settings.tmp")
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
