from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import decky

from handlers import known_nexus_domain
from mod_manager import Game, ModManager, to_payload
from nexus import NexusClient, NexusError, NexusKeyRequired, parse_nxm
# NOTE: do NOT name this module `settings` — Decky Loader ships a
# PyInstaller-bundled `decky_loader.settings` whose modules become importable
# at the bare name, shadowing any same-named module in py_modules/. We hit this
# in production; the symptom is "ImportError: cannot import name 'Settings'
# from 'decky_loader.settings'". Keep this module's filename namespaced.
from mm_settings import Settings


class Plugin:
    manager: ModManager
    settings: Settings
    nexus: NexusClient
    _jobs: set[asyncio.Task] = set()

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
        mod = await self.manager.install_archive(self._get_game(game_id), archive_path, display_name)
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

    async def nexus_browse(self, game_id: str, sort: str, compatible_only: bool = True) -> dict:
        domain, api_key = self._nexus_ctx(game_id, need_key=False)
        return self._compatible(game_id, await self.nexus.browse(domain, sort, api_key), compatible_only)

    async def nexus_search(self, game_id: str, query: str, compatible_only: bool = True) -> dict:
        domain, _ = self._nexus_ctx(game_id, need_key=False)
        return self._compatible(game_id, await self.nexus.search(domain, query), compatible_only)

    def _compatible(self, game_id: str, mods: list, compatible_only: bool) -> dict:
        version = self.manager.handler_for(game_id).game_version(self._get_game(game_id))
        if version and compatible_only:
            mods = [m for m in mods if m.updated_at[:10] >= version[1]]
        return {"version": version[0] if version else None, "mods": [m.to_dict() for m in mods]}

    async def nexus_mod_files(self, game_id: str, mod_id: int) -> list[dict]:
        domain, api_key = self._nexus_ctx(game_id)
        return [f.to_dict() for f in await self.nexus.mod_files(domain, int(mod_id), api_key)]

    async def nexus_install(self, game_id: str, mod_id: int, file_id: int, display_name: str) -> dict:
        domain, api_key = self._nexus_ctx(game_id)
        try:
            link = await self.nexus.download_link(domain, int(file_id), api_key)
        except NexusKeyRequired:
            return {"needs_nxm": True}
        return self._start_install(game_id, link, display_name, int(mod_id))

    async def nexus_install_nxm(self, game_id: str, url: str, display_name: str | None = None) -> dict:
        domain, api_key = self._nexus_ctx(game_id)
        nxm = parse_nxm(url)
        if nxm.domain != domain:
            raise NexusError(f"That link is for '{nxm.domain}', not this game ({domain}).")
        link = await self.nexus.download_link(domain, nxm.file_id, api_key, key=nxm.key, expires=nxm.expires)
        return self._start_install(game_id, link, display_name or f"Nexus mod {nxm.mod_id}", nxm.mod_id)

    def _start_install(self, game_id: str, link: str, name: str, mod_id: int) -> dict:
        """Download and install in the background, reporting through events."""
        job = uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        last = [0.0]

        def progress(fraction: float) -> None:
            if fraction - last[0] >= 0.02 or fraction == 1:
                last[0] = fraction
                asyncio.run_coroutine_threadsafe(decky.emit("install_progress", job, name, fraction), loop)

        async def run() -> None:
            archive = self.manager.data_dir / "cache" / Path(urlparse(link).path).name
            try:
                await self.nexus.download_to(link, archive, progress)
                await self.manager.install_archive(
                    self._get_game(game_id), str(archive), name, source="nexus", nexus_mod_id=mod_id,
                )
                await decky.emit("install_done", job, name, None)
            except Exception as e:
                decky.logger.exception("mod-manager: install of %s failed", name)
                await decky.emit("install_done", job, name, str(e))
            finally:
                archive.unlink(missing_ok=True)

        self._jobs.add(task := loop.create_task(run()))
        task.add_done_callback(self._jobs.discard)
        return {"job": job, "name": name}

    # ----------------------------- handler tools -------------------------

    async def script_merger(self, game_id: str, action: str) -> dict:
        """status / install / launch for the Witcher 3 Script Merger."""
        from tools.script_merger import script_merger_action

        game = self._get_game(game_id)
        api_key = self.settings.get("nexus_api_key") or None
        return await script_merger_action(action, Path(game.install_path), api_key=api_key)

    async def script_merger_native(self, game_id: str) -> dict:
        """Native diff3-based .ws merger for Witcher 3 — no Proton needed."""
        game, mods_payload = self._w3_merge_context(game_id)
        return await self.manager.handler_for(game.id).run_tool(
            "script_merger_native", game, mods=mods_payload,
        )

    async def settings_merger_native(self, game_id: str) -> dict:
        """Native diff3-based input.xml / userConfigDef.xml merger."""
        game, mods_payload = self._w3_merge_context(game_id)
        return await self.manager.handler_for(game.id).run_tool(
            "settings_merger_native",
            game,
            mods=mods_payload,
            data_dir=str(self.manager.data_dir),
        )

    async def remove_merged(self, game_id: str) -> dict:
        """Delete the merged-script mod and restore baseline settings files."""
        game = self._get_game(game_id)
        return await self.manager.handler_for(game.id).run_tool(
            "remove_merged", game, data_dir=str(self.manager.data_dir),
        )

    async def mods_settings_path(self, game_id: str) -> dict:
        """Report the resolved on-disk mods.settings path so users can debug."""
        game = self._get_game(game_id)
        return await self.manager.handler_for(game.id).run_tool(
            "mods_settings_path", game,
        )

    def _w3_merge_context(self, game_id: str):
        """Build the (game, mods_payload) tuple both merger RPCs need."""
        game = self._get_game(game_id)
        enabled = [m for m in self.manager.list_mods(game.id) if m.enabled]
        mods_payload = []
        for m in enabled:
            folders = {
                Path(rel).parts[1]
                for rel in m.files
                if len(Path(rel).parts) >= 2 and Path(rel).parts[0] in ("Mods", "mods")
            }
            for folder in folders:
                mods_payload.append({"id": m.id, "folder": folder, "name": m.name})
        return game, mods_payload

    # ----------------------------- helpers -------------------------------

    def _get_game(self, game_id: str) -> Game:
        for g in self.manager.discover_games():
            if g.id == game_id:
                return g
        raise LookupError(f"game not found: {game_id}")

    def _nexus_ctx(self, game_id: str, need_key: bool = True) -> tuple[str, str | None]:
        api_key = self.settings.get("nexus_api_key") or None
        if need_key and not api_key:
            raise NexusError("Add your Nexus API key in Settings first.")
        game = self._get_game(game_id)
        domain = known_nexus_domain(game.id) or self.nexus.resolve_domain(game.id, api_key)
        if not domain:
            hint = "" if api_key else " Adding your API key in Settings may help."
            raise NexusError(f"Couldn't find {game.name} on Nexus.{hint}")
        return domain, api_key

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
