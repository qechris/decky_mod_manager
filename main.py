from __future__ import annotations

import decky

from mod_manager import Game, ModManager, to_payload
from nexus import NexusClient, NexusError
from settings import Settings


class Plugin:
    manager: ModManager
    settings: Settings
    nexus: NexusClient

    # ----------------------------- discovery -----------------------------

    async def list_games(self) -> list[dict]:
        return to_payload(self.manager.discover_games())

    async def list_mods(self, game_id: str) -> list[dict]:
        return to_payload(self.manager.list_mods(game_id))

    async def get_handler_info(self, game_id: str) -> dict:
        handler = self.manager.handler_for(game_id)
        return {"name": handler.name, "tools": handler.tools()}

    # ----------------------------- install/uninstall ---------------------

    async def install_mod(
        self, game_id: str, archive_path: str, display_name: str | None = None
    ) -> dict:
        mod = await self.manager.install_archive(game_id, archive_path, display_name)
        return mod.to_dict()

    async def uninstall_mod(self, game_id: str, mod_id: str) -> bool:
        self.manager.uninstall_mod(self._get_game(game_id), mod_id)
        return True

    # ----------------------------- toggle --------------------------------

    async def enable_mod(self, game_id: str, mod_id: str) -> dict:
        return self.manager.enable_mod(self._get_game(game_id), mod_id).to_dict()

    async def disable_mod(self, game_id: str, mod_id: str) -> dict:
        return self.manager.disable_mod(self._get_game(game_id), mod_id).to_dict()

    # ----------------------------- settings ------------------------------

    async def get_settings(self) -> dict:
        return self.settings.as_dict_redacted()

    async def set_nexus_api_key(self, api_key: str) -> dict:
        self.settings.set("nexus_api_key", (api_key or "").strip())
        return self.settings.as_dict_redacted()

    # ----------------------------- nexus ---------------------------------

    async def nexus_resolve_domain(self, game_id: str) -> dict:
        game = self._get_game(game_id)
        api_key = self.settings.get("nexus_api_key") or None
        domain = self.nexus.resolve_domain(game.id, game.name, api_key)
        return {"domain": domain, "appid": game.id, "name": game.name}

    async def nexus_search(self, game_id: str, query: str) -> list[dict]:
        game = self._get_game(game_id)
        api_key = self.settings.get("nexus_api_key") or None
        domain = self.nexus.resolve_domain(game.id, game.name, api_key)
        if not domain:
            raise NexusError(f"No Nexus domain known for '{game.name}' (set API key in Settings).")
        hits = await self.nexus.search(domain, query, api_key=api_key)
        return [h.to_dict() for h in hits]

    async def nexus_trending(self, game_id: str) -> list[dict]:
        game, domain, api_key = self._nexus_ctx(game_id)
        return await self.nexus.trending(domain, api_key)

    async def nexus_mod_info(self, game_id: str, mod_id: int) -> dict:
        game, domain, api_key = self._nexus_ctx(game_id)
        return await self.nexus.mod_info(domain, int(mod_id), api_key)

    async def nexus_mod_files(self, game_id: str, mod_id: int) -> list[dict]:
        game, domain, api_key = self._nexus_ctx(game_id)
        files = await self.nexus.mod_files(domain, int(mod_id), api_key)
        return [f.to_dict() for f in files]

    async def nexus_install(
        self,
        game_id: str,
        mod_id: int,
        file_id: int,
        display_name: str,
        nxm_key: str | None = None,
        nxm_expires: int | None = None,
    ) -> dict:
        game, domain, api_key = self._nexus_ctx(game_id)
        link = await self.nexus.download_link(
            domain, int(mod_id), int(file_id), api_key,
            nxm_key=nxm_key, nxm_expires=nxm_expires,
        )
        cache_dir = self.manager.data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Filename comes from the URL path; ensure we keep an extension.
        from urllib.parse import urlparse
        from pathlib import Path as _P
        archive_name = _P(urlparse(link).path).name or f"nexus-{mod_id}-{file_id}.zip"
        archive_path = cache_dir / archive_name
        await self.nexus.download_to(link, archive_path)
        mod = await self.manager.install_archive(
            game.id, str(archive_path), display_name,
            source="nexus", nexus_mod_id=int(mod_id),
        )
        return mod.to_dict()

    # ----------------------------- handler tools -------------------------

    async def script_merger(self, game_id: str, action: str) -> dict:
        """status / install / launch for the Witcher 3 Script Merger."""
        from tools.script_merger import script_merger_action
        from pathlib import Path

        game = self._get_game(game_id)
        api_key = self.settings.get("nexus_api_key") or None
        return await script_merger_action(action, Path(game.install_path), api_key=api_key)

    async def script_merger_native(self, game_id: str) -> dict:
        """Native diff3-based .ws merger for Witcher 3 — no Proton needed."""
        game = self._get_game(game_id)
        enabled = [m for m in self.manager.list_mods(game.id) if m.enabled]
        # The handler needs each mod's on-disk folder name. We derive it from
        # the relative paths recorded at enable time.
        from pathlib import Path
        mods_payload = []
        for m in enabled:
            folders = {
                Path(rel).parts[1]
                for rel in m.files
                if len(Path(rel).parts) >= 2 and Path(rel).parts[0] in ("Mods", "mods")
            }
            for folder in folders:
                mods_payload.append({"id": m.id, "folder": folder, "name": m.name})
        return await self.manager.handler_for(game.id).run_tool(
            "script_merger_native", game, mods=mods_payload,
        )

    # ----------------------------- helpers -------------------------------

    def _get_game(self, game_id: str) -> Game:
        for g in self.manager.discover_games():
            if g.id == game_id:
                return g
        raise LookupError(f"game not found: {game_id}")

    def _nexus_ctx(self, game_id: str) -> tuple[Game, str, str]:
        game = self._get_game(game_id)
        api_key = self.settings.get("nexus_api_key")
        if not api_key:
            raise NexusError("Set your Nexus API key in Settings first.")
        domain = self.nexus.resolve_domain(game.id, game.name, api_key)
        if not domain:
            raise NexusError(f"No Nexus domain known for '{game.name}'.")
        return game, domain, api_key

    # ----------------------------- lifecycle -----------------------------

    async def _main(self) -> None:
        self.manager = ModManager()
        self.settings = Settings(self.manager.data_dir / "settings.json")
        self.nexus = NexusClient(self.manager.data_dir / "cache")
        decky.logger.info(
            "mod-manager: loaded, data dir=%s, nexus key set=%s",
            self.manager.data_dir, bool(self.settings.get("nexus_api_key")),
        )

    async def _unload(self) -> None:
        decky.logger.info("mod-manager: unloaded")

    async def _migration(self) -> None:
        pass
