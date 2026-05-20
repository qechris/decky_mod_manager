"""Core mod manager logic — game discovery, mod install/enable/disable/uninstall.

State layout (under ``data_dir``):

    state.json
    library/<game_id>/<mod_id>/...       (extracted mod payloads)
    backups/<game_id>/<mod_id>/...       (vanilla files displaced by enable)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tarfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import decky  # type: ignore
    _LOG = decky.logger
except Exception:  # running outside Decky (tests)
    import logging
    _LOG = logging.getLogger("mod_manager")


STEAM_VDF_APPMANIFEST_RE = re.compile(
    r'"appid"\s*"(?P<appid>\d+)".*?"name"\s*"(?P<name>[^"]+)".*?"installdir"\s*"(?P<installdir>[^"]+)"',
    re.DOTALL,
)
STEAM_VDF_LIBRARYFOLDER_RE = re.compile(r'"path"\s*"(?P<path>[^"]+)"')


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
        self._state = {
            game_id: {mod_id: Mod(**mod) for mod_id, mod in mods.items()}
            for game_id, mods in raw.items()
        }

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
                m = STEAM_VDF_APPMANIFEST_RE.search(text)
                if not m:
                    continue
                appid = m.group("appid")
                name = m.group("name")
                installdir = m.group("installdir")
                install_path = apps_dir / "common" / installdir
                if not install_path.exists():
                    continue
                seen[appid] = Game(id=appid, name=name, install_path=str(install_path))

        return sorted(seen.values(), key=lambda g: g.name.lower())

    # ----------------------------------------------------------- mod listing

    def list_mods(self, game_id: str) -> list[Mod]:
        return sorted(
            self._state.get(game_id, {}).values(),
            key=lambda m: m.name.lower(),
        )

    def get_mod(self, game_id: str, mod_id: str) -> Mod | None:
        return self._state.get(game_id, {}).get(mod_id)

    # ----------------------------------------------------------- install

    async def install_mod(
        self,
        game_id: str,
        archive_path: str,
        display_name: str | None = None,
    ) -> Mod:
        """Extract ``archive_path`` into the mod library. Does not enable it."""
        archive = Path(archive_path).expanduser()
        if not archive.exists():
            raise FileNotFoundError(f"archive not found: {archive}")

        mod_id = uuid.uuid4().hex[:12]
        name = display_name or archive.stem
        dest = self.library_dir / game_id / mod_id
        dest.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_extract_archive, archive, dest)
        _flatten_single_root(dest)

        mod = Mod(id=mod_id, name=name, game_id=game_id)
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
        game_root = Path(game.install_path)
        if not game_root.exists():
            raise FileNotFoundError(f"game install path missing: {game_root}")
        backup_root.mkdir(parents=True, exist_ok=True)

        applied: list[str] = []
        try:
            for src_file in _iter_files(src_root):
                rel = src_file.relative_to(src_root)
                target = game_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    # Back up vanilla file (only if not already a symlink we own)
                    if not target.is_symlink():
                        backup_path = backup_root / rel
                        backup_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(target), str(backup_path))
                    else:
                        target.unlink()
                os.symlink(src_file, target)
                applied.append(str(rel))
        except Exception:
            # Best-effort rollback of partial application
            for rel_str in applied:
                _safe_unlink(game_root / rel_str)
                bk = backup_root / rel_str
                if bk.exists():
                    (game_root / rel_str).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(bk), str(game_root / rel_str))
            raise

        mod.enabled = True
        mod.files = applied
        self._save_state()
        return mod

    def disable_mod(self, game: Game, mod_id: str) -> Mod:
        mod = self._require(game.id, mod_id)
        if not mod.enabled:
            return mod
        backup_root = self.backups_dir / game.id / mod_id
        game_root = Path(game.install_path)

        for rel_str in mod.files:
            target = game_root / rel_str
            _safe_unlink(target)
            backup_path = backup_root / rel_str
            if backup_path.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup_path), str(target))

        # Prune empty backup dirs
        if backup_root.exists():
            _prune_empty_dirs(backup_root)

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
    suffixes = "".join(archive.suffixes).lower()
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    elif name.endswith(".7z"):
        # Lazy import — only needed for 7z
        try:
            import py7zr  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "7z archives require the 'py7zr' package; install it or convert the mod to zip"
            ) from e
        with py7zr.SevenZipFile(archive) as sz:
            sz.extractall(dest)
    else:
        raise ValueError(f"unsupported archive format: {suffixes or archive.name}")


def _flatten_single_root(dest: Path) -> None:
    """If the archive extracted to a single top-level dir, hoist its contents."""
    entries = [p for p in dest.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for child in inner.iterdir():
            shutil.move(str(child), str(dest / child.name))
        inner.rmdir()


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() or p.is_symlink():
            yield p


def _safe_unlink(path: Path) -> None:
    try:
        if path.is_symlink() or path.exists():
            path.unlink()
    except OSError as e:
        _LOG.warning("mod-manager: failed to unlink %s: %s", path, e)


def _prune_empty_dirs(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames and Path(dirpath) != root:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


# Public helper to serialize Game/Mod for the frontend
def to_payload(obj: Any) -> Any:
    if isinstance(obj, (Game, Mod)):
        return obj.to_dict()
    if isinstance(obj, list):
        return [to_payload(o) for o in obj]
    return obj
