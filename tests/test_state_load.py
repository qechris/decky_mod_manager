"""Tests for ModManager._load_state on-disk-schema tolerance.

The state.json file can outlive multiple code versions. On users' decks we
saw entries like ``status: "ready"`` and ``error_message: null`` from an
earlier schema we no longer track. The loader must:

1. Accept extra unknown fields without raising (forward-compat — old code
   on newer state, or pruned fields the codebase has dropped).
2. Fill in defaults for fields that didn't exist when the state was written
   (backward-compat — newer code reading older state).

A regression here means the plugin crashes at __init__ time and the entire
frontend hangs on every RPC call. We've already lived through that once.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from mod_manager import ModManager  # noqa: E402


class LoadStateTolerantSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.data_dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_state(self, payload: dict) -> None:
        (self.data_dir / "state.json").write_text(json.dumps(payload))

    def test_unknown_fields_are_silently_dropped(self) -> None:
        # This is the actual shape we found on a user's deck — fields the
        # current schema doesn't know about must not crash __init__.
        self._write_state({
            "292030": {
                "abc123": {
                    "id": "abc123",
                    "name": "Some Mod",
                    "game_id": "292030",
                    "enabled": True,
                    "installed_at": 1779385466.83,
                    "files": [],
                    "source": "nexus",
                    "nexus_mod_id": 9647,
                    "status": "ready",          # ← unknown, was in old schema
                    "error_message": None,       # ← unknown, was in old schema
                }
            }
        })
        # Must not raise
        mm = ModManager(self.data_dir)
        mods = mm.list_mods("292030")
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0].name, "Some Mod")
        self.assertTrue(mods[0].enabled)

    def test_missing_optional_fields_get_defaults(self) -> None:
        # Older state may predate "source" and "nexus_mod_id" — should
        # quietly default them, not crash.
        self._write_state({
            "292030": {
                "abc123": {
                    "id": "abc123",
                    "name": "Ancient Mod",
                    "game_id": "292030",
                    "enabled": False,
                    "installed_at": 1700000000.0,
                    "files": [],
                    # no source, no nexus_mod_id
                }
            }
        })
        mm = ModManager(self.data_dir)
        mods = mm.list_mods("292030")
        self.assertEqual(mods[0].source, "local")
        self.assertIsNone(mods[0].nexus_mod_id)

    def test_corrupt_state_starts_fresh(self) -> None:
        (self.data_dir / "state.json").write_text("{not json")
        mm = ModManager(self.data_dir)  # must not raise
        self.assertEqual(mm.list_mods("292030"), [])

    def test_extra_AND_missing_combined(self) -> None:
        # Worst case: state has fields we don't recognize AND lacks fields
        # we expect. Both adaptations must apply.
        self._write_state({
            "292030": {
                "abc123": {
                    "id": "abc123",
                    "name": "Mixed",
                    "game_id": "292030",
                    "enabled": True,
                    "installed_at": 1700000000.0,
                    "files": [],
                    "status": "queued",
                    "priority": 5,  # another unknown field
                    # no source, no nexus_mod_id
                }
            }
        })
        mm = ModManager(self.data_dir)
        mods = mm.list_mods("292030")
        self.assertEqual(mods[0].source, "local")
        self.assertIsNone(mods[0].nexus_mod_id)
        self.assertTrue(mods[0].enabled)


if __name__ == "__main__":
    unittest.main()
