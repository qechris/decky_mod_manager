from __future__ import annotations

from typing import Any

import decky

from mod_manager import Game, ModManager, to_payload


class Plugin:
    manager: ModManager

    # -------- discovery --------

    async def list_games(self) -> list[dict]:
        return to_payload(self.manager.discover_games())

    async def list_mods(self, game_id: str) -> list[dict]:
        return to_payload(self.manager.list_mods(game_id))

    # -------- install/uninstall --------

    async def install_mod(
        self, game_id: str, archive_path: str, display_name: str | None = None
    ) -> dict:
        mod = await self.manager.install_mod(game_id, archive_path, display_name)
        return mod.to_dict()

    async def uninstall_mod(self, game_id: str, mod_id: str) -> bool:
        game = self._get_game(game_id)
        self.manager.uninstall_mod(game, mod_id)
        return True

    # -------- toggle --------

    async def enable_mod(self, game_id: str, mod_id: str) -> dict:
        mod = self.manager.enable_mod(self._get_game(game_id), mod_id)
        return mod.to_dict()

    async def disable_mod(self, game_id: str, mod_id: str) -> dict:
        mod = self.manager.disable_mod(self._get_game(game_id), mod_id)
        return mod.to_dict()

    # -------- helpers --------

    def _get_game(self, game_id: str) -> Game:
        for g in self.manager.discover_games():
            if g.id == game_id:
                return g
        raise LookupError(f"game not found: {game_id}")

    # -------- decky lifecycle --------

    async def _main(self) -> None:
        self.manager = ModManager()
        decky.logger.info("mod-manager: loaded, data dir=%s", self.manager.data_dir)

    async def _unload(self) -> None:
        decky.logger.info("mod-manager: unloaded")

    async def _migration(self) -> None:
        pass
