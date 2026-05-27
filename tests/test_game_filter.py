"""Tests for the Valve-runtime filter and Game.mod_count enrichment in
discover_games().

The user's Deck install had 15 appmanifests, of which 8 were Valve runtimes
(Proton variants, SteamLinuxRuntime, Steamworks Common). The mod manager
shouldn't show those — users can't mod runtimes. We also enrich each Game
with mod_count + enabled_mod_count from state so the games list can show
which games already have mods without an extra round-trip.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from mod_manager import _is_valve_runtime  # noqa: E402


class RuntimeFilterTests(unittest.TestCase):
    def test_known_appids_are_runtimes(self) -> None:
        # Real appids we observed on the user's deck
        for appid in ("228980", "1070560", "1391110", "1493710", "1628350",
                      "1826330", "2180100", "3658110", "4183110"):
            self.assertTrue(_is_valve_runtime(appid, "irrelevant"),
                            f"{appid} should be runtime")

    def test_real_games_not_filtered(self) -> None:
        # W3, Death Stranding, Halo MCC, Kingdom Come, Spyro
        for appid, installdir in [
            ("292030", "The Witcher 3"),
            ("1190460", "DEATH STRANDING"),
            ("976730", "Halo The Master Chief Collection"),
            ("379430", "KingdomComeDeliverance"),
            ("996580", "Spyro Reignited Trilogy"),
        ]:
            self.assertFalse(_is_valve_runtime(appid, installdir),
                             f"{appid}/{installdir} should NOT be runtime")

    def test_installdir_prefix_catches_unknown_proton(self) -> None:
        # Even if Steam ships a Proton release with an appid we don't
        # know about, the installdir name catches it
        self.assertTrue(_is_valve_runtime("9999999", "Proton 99.0"))
        self.assertTrue(_is_valve_runtime("8888888", "SteamLinuxRuntime_neon"))
        self.assertTrue(_is_valve_runtime("7777777", "Steamworks Shared"))


class GameModCountTests(unittest.TestCase):
    """End-to-end: state has mods, discover_games should reflect counts."""

    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.data_dir = Path(self._td.name)
        # Seed state.json with 2 mods for game 292030, 1 enabled
        (self.data_dir / "state.json").write_text(json.dumps({
            "292030": {
                "abc": {
                    "id": "abc", "name": "Mod A", "game_id": "292030",
                    "enabled": True, "installed_at": 1700000000.0,
                    "files": ["x"], "source": "nexus", "nexus_mod_id": 1,
                },
                "def": {
                    "id": "def", "name": "Mod B", "game_id": "292030",
                    "enabled": False, "installed_at": 1700000000.0,
                    "files": [], "source": "local", "nexus_mod_id": None,
                },
            }
        }))

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_mod_count_field_exists_and_serialises(self) -> None:
        from mod_manager import Game, ModManager
        mm = ModManager(self.data_dir)
        # Build a Game by hand to test serialization shape (discover_games
        # needs a real Steam install, which CI doesn't have)
        g = Game(id="292030", name="The Witcher 3", install_path="/x",
                 mod_count=2, enabled_mod_count=1)
        d = g.to_dict()
        self.assertEqual(d["mod_count"], 2)
        self.assertEqual(d["enabled_mod_count"], 1)
        # And the manager has the state we expect
        mods = mm.list_mods("292030")
        self.assertEqual(len(mods), 2)
        self.assertEqual(sum(1 for m in mods if m.enabled), 1)


if __name__ == "__main__":
    unittest.main()
