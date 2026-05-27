"""Tests for the native settings merger.

Covers:
- baseline snapshot semantics (first run captures vanilla, future runs reuse)
- end-to-end merge of input.xml from two mods (one non-overlapping, one
  conflicting → higher-priority wins)
- restore-from-baseline path that powers the "remove merged outputs" button
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from tools.settings_merger_native import (  # noqa: E402
    _baseline_path,
    _do_merge,
    _do_restore,
    _ensure_baseline,
)

REL_INPUT_XML = "bin/config/r4game/user_config_matrix/pc/input.xml"

VANILLA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<UserConfig>
  <Group id="Movement">
    <Var id="forward" displayName="Forward" />
  </Group>
  <Group id="Combat">
    <Var id="attack" displayName="Attack" />
  </Group>
</UserConfig>
"""

# Mod A adds a single new Group, far from any other change
MOD_A_XML = """<?xml version="1.0" encoding="UTF-8"?>
<UserConfig>
  <Group id="Movement">
    <Var id="forward" displayName="Forward" />
    <Var id="dodge" displayName="Quick Dodge (A)" />
  </Group>
  <Group id="Combat">
    <Var id="attack" displayName="Attack" />
  </Group>
</UserConfig>
"""

# Mod B touches Combat (different region from A's Movement change) — no conflict
MOD_B_XML = """<?xml version="1.0" encoding="UTF-8"?>
<UserConfig>
  <Group id="Movement">
    <Var id="forward" displayName="Forward" />
  </Group>
  <Group id="Combat">
    <Var id="attack" displayName="Attack" />
    <Var id="parry" displayName="Parry (B)" />
  </Group>
</UserConfig>
"""

# Mod C conflicts with Mod A on the dodge line — different displayName
MOD_C_XML = """<?xml version="1.0" encoding="UTF-8"?>
<UserConfig>
  <Group id="Movement">
    <Var id="forward" displayName="Forward" />
    <Var id="dodge" displayName="Quick Dodge (C wins)" />
  </Group>
  <Group id="Combat">
    <Var id="attack" displayName="Attack" />
  </Group>
</UserConfig>
"""


def _setup_install(install: Path, mod_files: dict[str, str]) -> None:
    """Drop the vanilla file plus a per-mod variant into a synthetic install."""
    (install / REL_INPUT_XML).parent.mkdir(parents=True, exist_ok=True)
    (install / REL_INPUT_XML).write_text(VANILLA_XML)
    for mod_name, content in mod_files.items():
        mod_path = install / "Mods" / mod_name / REL_INPUT_XML
        mod_path.parent.mkdir(parents=True, exist_ok=True)
        mod_path.write_text(content)


class BaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.install = self.tmp / "install"
        self.data_dir = self.tmp / "data"
        (self.install / REL_INPUT_XML).parent.mkdir(parents=True, exist_ok=True)
        (self.install / REL_INPUT_XML).write_text(VANILLA_XML)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_first_call_snapshots_vanilla(self) -> None:
        baseline = _ensure_baseline(self.install, self.data_dir, "292030", REL_INPUT_XML)
        self.assertIsNotNone(baseline)
        self.assertTrue(baseline.exists())
        self.assertEqual(baseline.read_text(), VANILLA_XML)

    def test_subsequent_calls_reuse_baseline(self) -> None:
        baseline = _ensure_baseline(self.install, self.data_dir, "292030", REL_INPUT_XML)
        # Mutate the install to simulate a merge writing to it
        (self.install / REL_INPUT_XML).write_text("// mutated by merger")
        again = _ensure_baseline(self.install, self.data_dir, "292030", REL_INPUT_XML)
        self.assertEqual(again, baseline)
        # Crucially: the baseline content is still VANILLA, not the mutation
        self.assertEqual(again.read_text(), VANILLA_XML)

    def test_missing_install_file_returns_none(self) -> None:
        (self.install / REL_INPUT_XML).unlink()
        self.assertIsNone(
            _ensure_baseline(self.install, self.data_dir, "292030", REL_INPUT_XML)
        )


class MergeOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.install = self.tmp / "install"
        self.data_dir = self.tmp / "data"
        self.mods_settings = self.tmp / "mods.settings"
        # Alpha=0, Beta=1, Gamma=2 (higher Priority = wins conflicts)
        self.mods_settings.write_text(
            "[modAlpha]\nEnabled=1\nPriority=0\n\n"
            "[modBeta]\nEnabled=1\nPriority=1\n\n"
            "[modGamma]\nEnabled=1\nPriority=2\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._td.cleanup()

    def _diff3_or_skip(self) -> None:
        if shutil.which("diff3") is None:
            self.skipTest("diff3 not available on PATH")

    def test_two_mods_non_overlapping_regions_clean_merge(self) -> None:
        _setup_install(self.install, {"modAlpha": MOD_A_XML, "modBeta": MOD_B_XML})
        self._diff3_or_skip()
        result = _do_merge(
            self.install, self.data_dir, "292030",
            [{"folder": "modAlpha"}, {"folder": "modBeta"}],
            self.mods_settings,
        )
        self.assertEqual(result["merged_files"], [REL_INPUT_XML])
        self.assertEqual(result["conflicts_auto_resolved"], [])
        merged = (self.install / REL_INPUT_XML).read_text()
        # Both additions present
        self.assertIn("Quick Dodge (A)", merged)
        self.assertIn("Parry (B)", merged)

    def test_overlapping_edits_auto_resolve_to_higher_priority(self) -> None:
        # Alpha (prio 0) and Gamma (prio 2) both edit the dodge line.
        # Gamma is higher priority — Gamma wins.
        _setup_install(self.install, {"modAlpha": MOD_A_XML, "modGamma": MOD_C_XML})
        self._diff3_or_skip()
        result = _do_merge(
            self.install, self.data_dir, "292030",
            [{"folder": "modAlpha"}, {"folder": "modGamma"}],
            self.mods_settings,
        )
        self.assertEqual(result["conflicts_auto_resolved"], [REL_INPUT_XML])
        merged = (self.install / REL_INPUT_XML).read_text()
        self.assertIn("Quick Dodge (C wins)", merged)
        self.assertNotIn("Quick Dodge (A)", merged)
        self.assertNotIn("<<<<<<<", merged)

    def test_only_one_mod_touches_file_skips_merge(self) -> None:
        # If only one mod touches the file, no merge needed — the engine
        # already loads our symlink fine.
        _setup_install(self.install, {"modAlpha": MOD_A_XML})
        self._diff3_or_skip()
        result = _do_merge(
            self.install, self.data_dir, "292030",
            [{"folder": "modAlpha"}],
            self.mods_settings,
        )
        self.assertEqual(result["merged_files"], [])


class RestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.install = self.tmp / "install"
        self.data_dir = self.tmp / "data"
        (self.install / REL_INPUT_XML).parent.mkdir(parents=True, exist_ok=True)
        (self.install / REL_INPUT_XML).write_text(VANILLA_XML)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_restore_writes_back_baseline_and_clears_dir(self) -> None:
        _ensure_baseline(self.install, self.data_dir, "292030", REL_INPUT_XML)
        # Simulate a merge writing junk to the install
        (self.install / REL_INPUT_XML).write_text("// merged garbage")
        result = _do_restore(self.install, self.data_dir, "292030")
        self.assertEqual(result["restored"], [REL_INPUT_XML])
        self.assertTrue(result["cleared_baseline_dir"])
        # Install file is back to vanilla
        self.assertEqual((self.install / REL_INPUT_XML).read_text(), VANILLA_XML)
        # Baseline dir is gone (so next merge starts fresh)
        self.assertFalse(_baseline_path(self.data_dir, "292030", REL_INPUT_XML).exists())

    def test_restore_with_no_baselines_is_noop(self) -> None:
        result = _do_restore(self.install, self.data_dir, "292030")
        self.assertEqual(result["restored"], [])
        self.assertFalse(result["cleared_baseline_dir"])


if __name__ == "__main__":
    unittest.main()
