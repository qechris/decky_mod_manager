"""Tests for the v3 Nexus client: nxm parsing, file picking, errors."""

from __future__ import annotations

import asyncio
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

import nexus  # noqa: E402
from handlers import get_handler, known_nexus_domain  # noqa: E402
from nexus import NexusClient, NexusError, NexusKeyRequired, parse_nxm  # noqa: E402


class ParseNxmTests(unittest.TestCase):
    def test_free_user_link(self) -> None:
        link = parse_nxm("nxm://witcher3/mods/484/files/31240?key=abc&expires=1700000000&user_id=1")
        self.assertEqual((link.domain, link.mod_id, link.file_id), ("witcher3", 484, 31240))
        self.assertEqual((link.key, link.expires), ("abc", 1700000000))

    def test_rejects_web_links(self) -> None:
        with self.assertRaises(NexusError):
            parse_nxm("https://www.nexusmods.com/witcher3/mods/484")


class GameSupportTests(unittest.TestCase):
    def test_known_games(self) -> None:
        self.assertEqual(known_nexus_domain("292030"), "witcher3")
        self.assertEqual(known_nexus_domain("1771300"), "kingdomcomedeliverance2")
        self.assertEqual(get_handler("379430").name, "kingdom_come")

    def test_unknown_game_is_generic(self) -> None:
        self.assertEqual(get_handler("1").name, "generic")
        self.assertIsNone(known_nexus_domain("1"))


class ModFilesTests(unittest.TestCase):
    def test_latest_visible_version_per_file_main_first(self) -> None:
        responses = {
            "/games/witcher3/mods/7": {"data": {"id": "99"}},
            "/mods/99/files": {"data": {"mod_files": [
                {"id": "1", "is_active": True},
                {"id": "2", "is_active": True},
                {"id": "3", "is_active": False},
            ]}},
            "/mod-files/1/versions": {"data": {"versions": [
                {"game_scoped_id": "10", "name": "Extra", "version": "1", "category": "optional", "position": "1.0"},
                {"game_scoped_id": "11", "name": "Extra", "version": "2", "category": "optional", "position": "2.0"},
            ]}},
            "/mod-files/2/versions": {"data": {"versions": [
                {"game_scoped_id": "20", "name": "Main", "version": "1", "category": "old_version", "position": "1.0"},
                {"game_scoped_id": "21", "name": "Main", "version": "2", "category": "main", "position": "2.0", "is_primary": True},
            ]}},
        }

        def fake(url: str, **_: object) -> dict:
            return responses[url.removeprefix(nexus.V3_BASE)]

        with TemporaryDirectory() as td, mock.patch.object(nexus, "_request_json", side_effect=fake):
            files = asyncio.run(NexusClient(Path(td)).mod_files("witcher3", 7, "k"))
        self.assertEqual([(f.file_id, f.version) for f in files], [(21, "2"), (11, "2")])


class ErrorMappingTests(unittest.TestCase):
    def _err(self, code: int, body: bytes) -> NexusError:
        return nexus._http_error(urllib.error.HTTPError("u", code, "", {}, io.BytesIO(body)))

    def test_free_user_needs_key(self) -> None:
        err = self._err(403, b'{"detail": "A download key is required"}')
        self.assertIsInstance(err, NexusKeyRequired)

    def test_bad_api_key(self) -> None:
        err = self._err(401, b"{}")
        self.assertNotIsInstance(err, NexusKeyRequired)
        self.assertIn("API key", str(err))


if __name__ == "__main__":
    unittest.main()
