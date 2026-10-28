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
import os
import re
import shutil
import tarfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, fields as dataclass_fields
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


# Steam ships runtime/compat tools as appmanifests in steamapps/, so they show
# up in our scan alongside actual games. Most users can't mod these and showing
# them as 8-of-15 entries in the picker is just clutter. We exclude two ways:
# (1) a small denylist of well-known Valve runtime appids, and (2) a
# heuristic match on the install directory name (every Proton release and SLR
# variant lives in a directory with one of these prefixes).
_VALVE_RUNTIME_APPIDS = {
    "228980",   # Steamworks Common Redistributables
    "1070560",  # Steam Linux Runtime 1.0 (scout)
    "1391110",  # Steam Linux Runtime 2.0 (soldier)
    "1493710",  # Proton Experimental
    "1628350",  # Steam Linux Runtime 3.0 (sniper)
    "1826330",  # Proton EasyAntiCheat Runtime
    "2180100",  # Proton Hotfix
    "3658110",  # Proton 10.0
    "4183110",  # Steam Linux Runtime 4.0
    # Older Protons that may still be installed:
    "858280", "961940", "1054830", "1113280", "1245040", "1420170", "1580130",
}

_RUNTIME_DIR_PREFIXES = (
    "Proton ",
    "SteamLinuxRuntime",
    "Steamworks Shared",
)


def _is_valve_runtime(appid: str, installdir: str) -> bool:
    if appid in _VALVE_RUNTIME_APPIDS:
        return True
    return any(installdir.startswith(p) for p in _RUNTIME_DIR_PREFIXES)


@dataclass
class Game:
    id: str           # appid as string
    name: str
    install_path: str
    mod_count: int = 0
    enabled_mod_count: int = 0

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
        # The on-disk schema evolves. Tolerate BOTH directions of skew:
        # - missing fields (older state, newer code) → fill with defaults
        # - extra fields (newer state, code that removed something, or
        #   abandoned experimental fields like a previous "status" /
        #   "error_message" we no longer track) → ignore them
        known_mod_fields = {f.name for f in dataclass_fields(Mod)}
        self._state = {}
        for game_id, mods in raw.items():
            self._state[game_id] = {}
            for mod_id, mod in mods.items():
                mod.setdefault("source", "local")
                mod.setdefault("nexus_mod_id", None)
                pruned = {k: v for k, v in mod.items() if k in known_mod_fields}
                self._state[game_id][mod_id] = Mod(**pruned)

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
                # Skip Valve runtimes/compat tools — users can't mod those and
                # they're noise in the picker (8/15 of a typical Deck install).
                if _is_valve_runtime(fields["appid"], fields["installdir"]):
                    continue
                install_path = apps_dir / "common" / fields["installdir"]
                if not install_path.exists():
                    continue
                mods = self._state.get(fields["appid"], {})
                seen[fields["appid"]] = Game(
                    id=fields["appid"],
                    name=fields["name"],
                    install_path=str(install_path),
                    mod_count=len(mods),
                    enabled_mod_count=sum(1 for m in mods.values() if m.enabled),
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
        game: Game,
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
        dest = self.library_dir / game.id / mod_id
        dest.mkdir(parents=True, exist_ok=True)

        try:
            await asyncio.to_thread(_extract_archive, archive, dest)
            self.handler_for(game.id).post_install_payload(dest, Path(game.install_path))
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise

        mod = Mod(id=mod_id, name=name, game_id=game.id, source=source, nexus_mod_id=nexus_mod_id)
        self._state.setdefault(game.id, {})[mod_id] = mod
        self._save_state()
        _LOG.info("mod-manager: installed mod %s (%s) for game %s", name, mod_id, game.id)
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
        files = self._release_overwritten(game, mod, backup_root)
        self.handler_for(game.id).disable(game, files, backup_root)
        self._relink_shadowed(game, mod, files)
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

    def _release_overwritten(self, game: Game, mod: Mod, backup_root: Path) -> list[str]:
        """Drop files a later-enabled mod has since replaced, handing our
        backup of the vanilla file to that mod so disabling it restores it."""
        own_root = (self.library_dir / game.id / mod.id).resolve()
        kept: list[str] = []
        for rel in mod.files:
            target = Path(game.install_path) / rel
            if not target.is_symlink() or Path(os.readlink(target)).resolve().is_relative_to(own_root):
                kept.append(rel)
                continue
            owner = next((m for m in self.list_mods(game.id) if m.enabled and m.id != mod.id and rel in m.files), None)
            backup = backup_root / rel
            if owner and backup.exists():
                dest = self.backups_dir / game.id / owner.id / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup), str(dest))
        return kept

    def _relink_shadowed(self, game: Game, mod: Mod, files: list[str]) -> None:
        """Point files this mod had replaced back at the other enabled mod
        that also ships them."""
        for other in self.list_mods(game.id):
            if not other.enabled or other.id == mod.id:
                continue
            for rel in set(files) & set(other.files):
                src = self.library_dir / game.id / other.id / rel
                target = Path(game.install_path) / rel
                if src.exists() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(src, target)

    def _require(self, game_id: str, mod_id: str) -> Mod:
        mod = self.get_mod(game_id, mod_id)
        if mod is None:
            raise KeyError(f"unknown mod {mod_id} for game {game_id}")
        return mod


# ---------------------------------------------------------------- utilities


def _archive_kind(archive: Path) -> str:
    """Nexus CDN files can have no extension, so check the file header first."""
    with archive.open("rb") as f:
        head = f.read(8)
    if head.startswith(b"PK"):
        return "zip"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"Rar!"):
        return "rar"
    if tarfile.is_tarfile(archive):
        return "tar"
    name = archive.name.lower()
    return next((k for k in ("zip", "7z", "rar") if name.endswith("." + k)), "")


def _extract_archive(archive: Path, dest: Path) -> None:
    kind = _archive_kind(archive)
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif kind == "tar":
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    elif kind == "7z":
        _extract_via_python_or_subprocess(
            archive, dest,
            py_module="py7zr",
            py_extract=lambda mod, a, d: mod.SevenZipFile(a).extractall(d),
            cli_bins=("7z", "7zz", "7za", "7zr"),
            cli_args=("x", "-y", "-o{dest}", "{archive}"),
        )
    elif kind == "rar":
        _extract_via_python_or_subprocess(
            archive, dest,
            py_module="rarfile",
            py_extract=lambda mod, a, d: mod.RarFile(a).extractall(d),
            cli_bins=("unrar", "rar"),
            cli_args=("x", "-y", "-o+", "{archive}", "{dest}/"),
        )
    else:
        raise ValueError(f"unsupported archive format: {archive.name}")


def _extract_via_python_or_subprocess(
    archive: Path,
    dest: Path,
    *,
    py_module: str,
    py_extract,
    cli_bins: tuple[str, ...],
    cli_args: tuple[str, ...],
) -> None:
    """Try the pure-Python extractor first; fall back to a CLI binary.

    Decky's plugin Python is PyInstaller-frozen and ships with no third-
    party extractors. SteamOS does ship ``7z`` / ``unrar`` system-wide, so
    we shell out to those when the Python module isn't importable. This is
    the difference between "Nexus install silently fails" and "Nexus
    install works for every common archive format users encounter."
    """
    import importlib
    import subprocess as _sp
    try:
        mod = importlib.import_module(py_module)
        dest.mkdir(parents=True, exist_ok=True)
        py_extract(mod, archive, dest)
        return
    except ImportError:
        pass  # fall through to CLI
    cli = next((shutil.which(b) for b in cli_bins if shutil.which(b)), None)
    if cli is None:
        raise RuntimeError(
            f"can't extract {archive.name}: neither the Python '{py_module}' "
            f"module nor any of {list(cli_bins)} is available on this system"
        )
    dest.mkdir(parents=True, exist_ok=True)
    args = [cli] + [a.format(archive=str(archive), dest=str(dest)) for a in cli_args]
    result = _sp.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{cli_bins[0]} failed (rc={result.returncode}) extracting "
            f"{archive.name}:\n{result.stderr[:500] or result.stdout[:500]}"
        )


def to_payload(obj: Any) -> Any:
    if isinstance(obj, (Game, Mod)):
        return obj.to_dict()
    if isinstance(obj, list):
        return [to_payload(o) for o in obj]
    return obj
