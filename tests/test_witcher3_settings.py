"""Tests for mods.settings location + INI io.

The "location" piece is the second-biggest root cause we fixed: the file
needs to land in the Proton prefix's Documents dir, not the game install.
"""

from __future__ import annotations

import configparser
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from handlers.witcher3 import (  # noqa: E402
    Witcher3Handler,
    _ensure_mods_settings_entries,
    _mods_settings_path,
    _remove_mods_settings_entries,
    _w3_documents_dir,
)


@dataclass
class FakeGame:
    id: str
    install_path: str


class ModsSettingsPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        # Simulate a Steam library layout
        self.steamapps = self.tmp / "steamapps"
        self.install = self.steamapps / "common" / "The Witcher 3"
        self.install.mkdir(parents=True)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_returns_prefix_documents_when_prefix_exists(self) -> None:
        prefix = self.steamapps / "compatdata" / "292030" / "pfx"
        (prefix / "drive_c" / "users" / "steamuser").mkdir(parents=True)
        out = _w3_documents_dir(self.install, "292030")
        self.assertEqual(
            out,
            prefix / "drive_c" / "users" / "steamuser" / "Documents" / "The Witcher 3",
        )

    def test_returns_none_without_prefix(self) -> None:
        self.assertIsNone(_w3_documents_dir(self.install, "292030"))

    def test_mods_settings_path_prefers_prefix(self) -> None:
        prefix = self.steamapps / "compatdata" / "292030" / "pfx"
        (prefix / "drive_c" / "users" / "steamuser").mkdir(parents=True)
        path = _mods_settings_path(self.install, "292030")
        self.assertEqual(path.name, "mods.settings")
        self.assertIn("compatdata/292030", str(path))
        self.assertIn("Documents/The Witcher 3", str(path))

    def test_mods_settings_path_falls_back_to_install(self) -> None:
        # No prefix dir → fall back to <install>/Mods/mods.settings
        path = _mods_settings_path(self.install, "292030")
        self.assertEqual(path, self.install / "Mods" / "mods.settings")

    def test_install_path_not_under_steamapps_returns_none(self) -> None:
        unusual = self.tmp / "Games" / "TheWitcher3"
        unusual.mkdir(parents=True)
        self.assertIsNone(_w3_documents_dir(unusual, "292030"))


class ModsSettingsIoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.path = Path(self._td.name) / "mods.settings"

    def tearDown(self) -> None:
        self._td.cleanup()

    def _parse(self) -> configparser.ConfigParser:
        cp = configparser.ConfigParser()
        cp.optionxform = str
        cp.read(self.path, encoding="utf-8-sig")
        return cp

    def test_ensure_creates_file_with_entries(self) -> None:
        _ensure_mods_settings_entries(self.path, ["modAlpha", "modBeta"], enabled=True)
        self.assertTrue(self.path.exists())
        cp = self._parse()
        self.assertEqual(cp["modAlpha"]["Enabled"], "1")
        self.assertEqual(cp["modBeta"]["Enabled"], "1")
        self.assertNotEqual(cp["modAlpha"]["Priority"], cp["modBeta"]["Priority"])

    def test_ensure_assigns_increasing_priorities(self) -> None:
        _ensure_mods_settings_entries(self.path, ["modA"], enabled=True)
        _ensure_mods_settings_entries(self.path, ["modB"], enabled=True)
        _ensure_mods_settings_entries(self.path, ["modC"], enabled=True)
        cp = self._parse()
        prios = sorted(int(cp[s]["Priority"]) for s in ("modA", "modB", "modC"))
        self.assertEqual(prios, [0, 1, 2])

    def test_ensure_is_idempotent_on_existing_entry(self) -> None:
        _ensure_mods_settings_entries(self.path, ["modA"], enabled=False)
        cp = self._parse()
        self.assertEqual(cp["modA"]["Enabled"], "0")
        _ensure_mods_settings_entries(self.path, ["modA"], enabled=True)
        cp = self._parse()
        self.assertEqual(cp["modA"]["Enabled"], "1")

    def test_remove_drops_sections(self) -> None:
        _ensure_mods_settings_entries(self.path, ["modA", "modB"], enabled=True)
        _remove_mods_settings_entries(self.path, ["modA"])
        cp = self._parse()
        self.assertFalse(cp.has_section("modA"))
        self.assertTrue(cp.has_section("modB"))

    def test_remove_on_missing_file_is_noop(self) -> None:
        _remove_mods_settings_entries(self.path, ["modA"])  # no exception


class HandlerToolsAdvertisedTests(unittest.TestCase):
    def test_handler_advertises_both_mergers(self) -> None:
        ids = [t["id"] for t in Witcher3Handler().tools()]
        self.assertIn("script_merger_status", ids)
        self.assertIn("script_merger_native", ids)


if __name__ == "__main__":
    unittest.main()
