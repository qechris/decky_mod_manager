"""Handler interface and shared helpers."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


@dataclass
class EnableResult:
    """Files written/changed inside the game directory, as paths *relative* to it."""

    files: list[str]


class GameLike(Protocol):
    id: str
    install_path: str


class BaseHandler:
    """Default behavior: a handler that does nothing extra over the symlink default.

    Subclasses override hooks. The contract is intentionally narrow:

    * ``enable(game, mod_root, backup_root)`` — apply this mod's payload to the
      game install. Must back up any vanilla files it would overwrite under
      ``backup_root`` (mirroring their relative paths). Returns the list of
      paths it touched, again relative to the game dir.
    * ``disable(game, mod_files, backup_root)`` — reverse the above.
    * ``post_install_payload(payload_root)`` — adjust the extracted archive
      tree before it's recorded in the library (e.g. normalize layout).
    """

    name: str = "generic"

    # ----- lifecycle hooks for the extracted payload ---------------------

    def post_install_payload(self, payload_root: Path) -> None:
        flatten_single_root(payload_root)

    # ----- enable / disable -- subclasses override these -----------------

    def enable(self, game: GameLike, payload_root: Path, backup_root: Path) -> EnableResult:
        raise NotImplementedError

    def disable(self, game: GameLike, files: list[str], backup_root: Path) -> None:
        raise NotImplementedError

    # ----- optional tools surfaced in the UI -----------------------------

    def tools(self) -> list[dict]:
        """Return a list of ``{id, label, description}`` actions this handler
        wants to expose. Generic handler returns none. Game-specific
        handlers (Witcher 3 etc) advertise things like 'Run Script Merger'."""
        return []

    async def run_tool(self, tool_id: str, game: GameLike, **kwargs) -> dict:
        raise KeyError(f"tool not supported: {tool_id}")


# --------------------------------------------------------------- utilities

def flatten_single_root(dest: Path) -> bool:
    """If a fresh extraction produced exactly one top-level dir, hoist its
    contents up so the payload root maps directly to the game-install root.

    Returns ``True`` if it hoisted something, ``False`` if it was a no-op
    (because the payload has zero, multiple, or non-directory top-level
    entries). Callers that need to handle the multi-entry case differently
    should check the return value rather than assuming this normalized the
    layout.
    """
    entries = [p for p in dest.iterdir() if not p.name.startswith(".")]
    if len(entries) != 1 or not entries[0].is_dir():
        return False
    inner = entries[0]
    for child in list(inner.iterdir()):
        shutil.move(str(child), str(dest / child.name))
    inner.rmdir()
    return True


def iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() or p.is_symlink():
            yield p


def safe_unlink(path: Path) -> None:
    try:
        if path.is_symlink() or path.exists():
            path.unlink()
    except OSError:
        pass


def prune_empty_dirs(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames and Path(dirpath) != root:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def symlink_tree(src_root: Path, dest_root: Path, backup_root: Path) -> list[str]:
    """Symlink every file from ``src_root`` into ``dest_root`` mirroring its
    relative layout. Any pre-existing file at the destination is moved into
    ``backup_root`` first (preserving structure). Returns relative path strings.
    """
    applied: list[str] = []
    try:
        for src_file in iter_files(src_root):
            rel = src_file.relative_to(src_root)
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if not target.is_symlink():
                    bp = backup_root / rel
                    bp.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(bp))
                else:
                    target.unlink()
            os.symlink(src_file, target)
            applied.append(str(rel))
    except Exception:
        # Best-effort rollback
        for rel_str in applied:
            t = dest_root / rel_str
            safe_unlink(t)
            bp = backup_root / rel_str
            if bp.exists():
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(bp), str(t))
        raise
    return applied


def restore_tree(dest_root: Path, files: list[str], backup_root: Path) -> None:
    for rel_str in files:
        target = dest_root / rel_str
        safe_unlink(target)
        bp = backup_root / rel_str
        if bp.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bp), str(target))
    if backup_root.exists():
        prune_empty_dirs(backup_root)
