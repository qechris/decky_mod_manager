"""Generic file-mirror handler — what every mod gets unless overridden."""

from __future__ import annotations

from pathlib import Path

from handlers.base import BaseHandler, EnableResult, GameLike, restore_tree, symlink_tree


class GenericHandler(BaseHandler):
    name = "generic"

    def enable(self, game: GameLike, payload_root: Path, backup_root: Path) -> EnableResult:
        game_root = Path(game.install_path)
        if not game_root.exists():
            raise FileNotFoundError(f"game install path missing: {game_root}")
        backup_root.mkdir(parents=True, exist_ok=True)
        files = symlink_tree(payload_root, game_root, backup_root)
        return EnableResult(files=files)

    def disable(self, game: GameLike, files: list[str], backup_root: Path) -> None:
        restore_tree(Path(game.install_path), files, backup_root)
