"""Core mod manager — game discovery, install/enable/disable/uninstall.

Per-game behavior is delegated to ``handlers.get_handler(appid)``. This module
owns: state persistence, the on-disk library layout, archive extraction, and
the Steam library scan.

State layout (under ``data_dir``):

    state.json
    library/<game_id>/<mod_id>/...       (extracted mod payloads)
    backups/<game_id>/<mod_id>/...       (vanilla files displaced by enable)
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tarfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from handlers import BaseHandler, get_handler

try:
    import decky  # type: ignore
    _LOG = decky.logger
except Exception:  # running outside Decky (tests)
    import logging
    _LOG = logging.getLogger("mod_manager")


# Parse appmanifest_*.acf top-level fields independently. The previous
# single-regex-with-DOTALL approach assumed a specific field order and could
# in principle false-match if a name field contained the literal "installdir".
# Three targeted regexes (one per field, anchored to start-of-line) are
# robust to field reordering and to ill-behaved values.
_STEAM_VDF_APPID_RE = re.compile(r'^\s*"appid"\s*"(?P<appid>\d+)"', re.MULTILINE)
_STEAM_VDF_NAME_RE = re.compile(r'^\s*"name"\s*"(?P<name>[^"]+)"', re.MULTILINE)
_STEAM_VDF_INSTALLDIR_RE = re.compile(
    r'^\s*"installdir"\s*"(?P<installdir>[^"]+)"', re.MULTILINE
)
STEAM_VDF_LIBRARYFOLDER_RE = re.compile(r'"path"\s*"(?P<path>[^"]+)"')


def _parse_appmanifest(text: str) -> dict[str, str] | None:
    """Extract appid/name/installdir from an appmanifest_*.acf body.
    Returns ``None`` if any required field is missing."""
    appid = _STEAM_VDF_APPID_RE.search(text)
    name = _STEAM_VDF_NAME_RE.search(text)
    installdir = _STEAM_VDF_INSTALLDIR_RE.search(text)
    if not (appid and name and installdir):
        return None
    return {
        "appid": appid.group("appid"),
        "name": name.group("name"),
        "installdir": installdir.group("installdir"),
    }


@dataclass
class Game:
    id: str           # appid as string
    name: str
    install_path: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Mod:
    id: str
    name: str
    game_id: str
    enabled: bool = False
    installed_at: float = field(default_factory=time.time)
    files: list[str] = field(default_factory=list)  # relative paths inside game dir
    source: str = "local"  # "local" or "nexus"
    nexus_mod_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ModManager:
    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            data_dir = Path.home() / ".local" / "share" / "decky-mod-manager"
        self.data_dir = Path(data_dir)
        self.library_dir = self.data_dir / "library"
        self.backups_dir = self.data_dir / "backups"
        self.state_file = self.data_dir / "state.json"
        for d in (self.library_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, dict[str, Mod]] = {}  # game_id -> mod_id -> Mod
        self._load_state()

    # ------------------------------------------------------------------ state

    def _load_state(self) -> None:
        if not self.state_file.exists():
            self._state = {}
            return
        try:
            raw = json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            _LOG.warning("mod-manager: state load failed (%s); starting fresh", e)
            self._state = {}
            return
        self._state = {}
        for game_id, mods in raw.items():
            self._state[game_id] = {}
            for mod_id, mod in mods.items():
                # Tolerate older state lacking new fields.
                mod.setdefault("source", "local")
                mod.setdefault("nexus_mod_id", None)
                self._state[game_id][mod_id] = Mod(**mod)

    def _save_state(self) -> None:
        serializable = {
            game_id: {mod_id: m.to_dict() for mod_id, m in mods.items()}
            for game_id, mods in self._state.items()
        }
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(serializable, indent=2))
        tmp.replace(self.state_file)

    # ------------------------------------------------------------- discovery

    def discover_games(self) -> list[Game]:
        """Scan Steam library folders for installed games."""
        steam_root = Path.home() / ".steam" / "steam"
        if not steam_root.exists():
            steam_root = Path.home() / ".local" / "share" / "Steam"
        if not steam_root.exists():
            return []

        library_paths = [steam_root]
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                text = vdf.read_text(errors="ignore")
                for m in STEAM_VDF_LIBRARYFOLDER_RE.finditer(text):
                    p = Path(m.group("path"))
                    if p.exists() and p not in library_paths:
                        library_paths.append(p)
            except OSError as e:
                _LOG.warning("mod-manager: failed reading %s: %s", vdf, e)

        seen: dict[str, Game] = {}
        for lib in library_paths:
            apps_dir = lib / "steamapps"
            if not apps_dir.is_dir():
                continue
            for manifest in apps_dir.glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(errors="ignore")
                except OSError:
                    continue
                fields = _parse_appmanifest(text)
                if fields is None:
                    continue
                install_path = apps_dir / "common" / fields["installdir"]
                if not install_path.exists():
                    continue
                seen[fields["appid"]] = Game(
                    id=fields["appid"],
                    name=fields["name"],
                    install_path=str(install_path),
                )

        return sorted(seen.values(), key=lambda g: g.name.lower())

    # ----------------------------------------------------------- mod listing

    def list_mods(self, game_id: str) -> list[Mod]:
        return sorted(
            self._state.get(game_id, {}).values(),
            key=lambda m: m.name.lower(),
        )

    def get_mod(self, game_id: str, mod_id: str) -> Mod | None:
        return self._state.get(game_id, {}).get(mod_id)

    def handler_for(self, game_id: str) -> BaseHandler:
        return get_handler(game_id)

    # ----------------------------------------------------------- install

    async def install_archive(
        self,
        game_id: str,
        archive_path: str,
        display_name: str | None = None,
        *,
        source: str = "local",
        nexus_mod_id: int | None = None,
    ) -> Mod:
        archive = Path(archive_path).expanduser()
        if not archive.exists():
            raise FileNotFoundError(f"archive not found: {archive}")

        mod_id = uuid.uuid4().hex[:12]
        name = display_name or archive.stem
        dest = self.library_dir / game_id / mod_id
        dest.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_extract_archive, archive, dest)
        self.handler_for(game_id).post_install_payload(dest)

        mod = Mod(id=mod_id, name=name, game_id=game_id, source=source, nexus_mod_id=nexus_mod_id)
        self._state.setdefault(game_id, {})[mod_id] = mod
        self._save_state()
        _LOG.info("mod-manager: installed mod %s (%s) for game %s", name, mod_id, game_id)
        return mod

    # ----------------------------------------------------------- enable/disable

    def enable_mod(self, game: Game, mod_id: str) -> Mod:
        mod = self._require(game.id, mod_id)
        if mod.enabled:
            return mod
        src_root = self.library_dir / game.id / mod_id
        backup_root = self.backups_dir / game.id / mod_id
        result = self.handler_for(game.id).enable(game, src_root, backup_root)
        mod.enabled = True
        mod.files = result.files
        self._save_state()
        return mod

    def disable_mod(self, game: Game, mod_id: str) -> Mod:
        mod = self._require(game.id, mod_id)
        if not mod.enabled:
            return mod
        backup_root = self.backups_dir / game.id / mod_id
        self.handler_for(game.id).disable(game, mod.files, backup_root)
        mod.enabled = False
        mod.files = []
        self._save_state()
        return mod

    # ----------------------------------------------------------- uninstall

    def uninstall_mod(self, game: Game, mod_id: str) -> None:
        mod = self._require(game.id, mod_id)
        if mod.enabled:
            self.disable_mod(game, mod_id)
        shutil.rmtree(self.library_dir / game.id / mod_id, ignore_errors=True)
        shutil.rmtree(self.backups_dir / game.id / mod_id, ignore_errors=True)
        del self._state[game.id][mod_id]
        if not self._state[game.id]:
            del self._state[game.id]
        self._save_state()

    # ----------------------------------------------------------- helpers

    def _require(self, game_id: str, mod_id: str) -> Mod:
        mod = self.get_mod(game_id, mod_id)
        if mod is None:
            raise KeyError(f"unknown mod {mod_id} for game {game_id}")
        return mod


# ---------------------------------------------------------------- utilities


def _extract_archive(archive: Path, dest: Path) -> None:
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    elif name.endswith(".7z"):
        try:
            import py7zr  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "7z archives require the 'py7zr' package; install it or convert the mod to zip"
            ) from e
        with py7zr.SevenZipFile(archive) as sz:
            sz.extractall(dest)
    elif name.endswith(".rar"):
        try:
            import rarfile  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "rar archives require the 'rarfile' package; install it or convert the mod to zip"
            ) from e
        with rarfile.RarFile(archive) as rf:
            rf.extractall(dest)
    else:
        raise ValueError(f"unsupported archive format: {archive.name}")


def to_payload(obj: Any) -> Any:
    if isinstance(obj, (Game, Mod)):
        return obj.to_dict()
    if isinstance(obj, list):
        return [to_payload(o) for o in obj]
    return obj
