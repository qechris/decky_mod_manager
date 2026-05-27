"""Tests for the native script merger.

We test the encoding plumbing and the discovery/orchestration logic with a
synthetic install + two mods. The actual diff3 invocation is exercised end-
to-end so this test is meaningful, but we steer clear of constructing
3-way conflicts to keep us from depending on the user's TODO function.

A separate test class targets ``_resolve_conflicts_pick_later`` directly —
those tests are skipped until the user implements the function (the
``NotImplementedError`` is the signal).
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from tools.script_merger_native import (  # noqa: E402
    _CONFLICT_RE,
    _detect_encoding,
    _do_merge,
    _resolve_conflicts_pick_later,
    _write_utf16,
)


class EncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_utf16_roundtrip(self) -> None:
        p = self.tmp / "x.ws"
        _write_utf16(p, "function foo() {\n  // hi\n}\n")
        self.assertEqual(_detect_encoding(p), "utf-16")

    def test_latin1_no_bom_detected_as_latin1(self) -> None:
        p = self.tmp / "x.ws"
        p.write_bytes(b"some scripty stuff\n")
        self.assertEqual(_detect_encoding(p), "latin1")

    def test_utf8_bom_detected(self) -> None:
        p = self.tmp / "x.ws"
        p.write_bytes(b"\xef\xbb\xbfhello\n")
        self.assertEqual(_detect_encoding(p), "utf-8-sig")


class MergeOrchestrationTests(unittest.TestCase):
    """End-to-end merge with two mods that touch different files — no
    conflicts arise, so we never exercise the TODO function."""

    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.install = Path(self._td.name) / "The Witcher 3"
        # Long enough vanilla that two mods can edit non-overlapping regions.
        vanilla_body = "// vanilla header\n" + "\n".join(
            f"function fn{i}() {{ return {i}; }}" for i in range(40)
        ) + "\n// vanilla footer\n"
        vanilla_script = (
            self.install / "content" / "content0" / "scripts" / "game" / "x.ws"
        )
        _write_utf16(vanilla_script, vanilla_body)
        # Mod A modifies fn0 only.
        a_body = vanilla_body.replace(
            "function fn0() { return 0; }",
            "function fn0() { return 999; /* alpha */ }",
        )
        _write_utf16(
            self.install / "Mods" / "modAlpha" / "content" / "scripts" / "game" / "x.ws",
            a_body,
        )
        # Mod B modifies a different file y.ws — no conflict at all
        _write_utf16(
            self.install / "Mods" / "modBeta" / "content" / "scripts" / "game" / "y.ws",
            "// beta y\nfunction y() {}\n",
        )

        self.mods_settings = self.install / "mods.settings"
        # alpha=0, beta=1
        self.mods_settings.write_text(
            "[modAlpha]\nEnabled=1\nPriority=0\n\n[modBeta]\nEnabled=1\nPriority=1\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_no_overlap_means_nothing_to_merge(self) -> None:
        # When each .ws file is in only one mod, the engine can already load
        # it correctly — the merger should produce an empty output.
        mods = [
            {"folder": "modAlpha"},
            {"folder": "modBeta"},
        ]
        if shutil.which("diff3") is None:
            self.skipTest("diff3 not available on PATH")
        result = _do_merge(self.install, mods, self.mods_settings)
        self.assertEqual(result["merged_files"], [])
        self.assertEqual(result["conflicts_auto_resolved"], [])

    def test_overlapping_edits_autoresolve_to_higher_priority(self) -> None:
        # Both mods edit fn0, in conflicting ways. Beta has higher priority
        # (Priority=1 > Priority=0) so its edit should win in the merge.
        vanilla = (
            self.install / "content" / "content0" / "scripts" / "game" / "x.ws"
        ).read_text(encoding="utf-16")
        beta_x_body = vanilla.replace(
            "function fn0() { return 0; }",
            "function fn0() { return -1; /* beta wins */ }",
        )
        _write_utf16(
            self.install / "Mods" / "modBeta" / "content" / "scripts" / "game" / "x.ws",
            beta_x_body,
        )
        if shutil.which("diff3") is None:
            self.skipTest("diff3 not available on PATH")
        result = _do_merge(
            self.install,
            [{"folder": "modAlpha"}, {"folder": "modBeta"}],
            self.mods_settings,
        )
        self.assertIn("content/scripts/game/x.ws", result["merged_files"])
        self.assertEqual(
            result["conflicts_auto_resolved"], ["content/scripts/game/x.ws"]
        )
        merged_body = (
            self.install / "Mods" / "mod0000_DeckyMerged" / "content" / "scripts" / "game" / "x.ws"
        ).read_text(encoding="utf-16")
        # Beta won the conflict — alpha's edit was dropped at the conflict site.
        self.assertIn("/* beta wins */", merged_body)
        self.assertNotIn("/* alpha */", merged_body)
        # No leftover conflict markers
        self.assertNotIn("<<<<<<<", merged_body)
        self.assertNotIn(">>>>>>>", merged_body)

    def test_two_mods_same_file_non_overlapping_regions_auto_merge(self) -> None:
        # modBeta also touches x.ws but in a different fn (fn30, far from
        # alpha's fn0). diff3 should auto-merge with NO conflict.
        beta_x_body = (
            self.install / "content" / "content0" / "scripts" / "game" / "x.ws"
        ).read_text(encoding="utf-16").replace(
            "function fn30() { return 30; }",
            "function fn30() { return 7777; /* beta */ }",
        )
        _write_utf16(
            self.install / "Mods" / "modBeta" / "content" / "scripts" / "game" / "x.ws",
            beta_x_body,
        )
        if shutil.which("diff3") is None:
            self.skipTest("diff3 not available on PATH")
        result = _do_merge(
            self.install,
            [{"folder": "modAlpha"}, {"folder": "modBeta"}],
            self.mods_settings,
        )
        self.assertIn("content/scripts/game/x.ws", result["merged_files"])
        self.assertEqual(result["conflicts_auto_resolved"], [])
        merged = self.install / "Mods" / "mod0000_DeckyMerged" / "content" / "scripts" / "game" / "x.ws"
        self.assertTrue(merged.exists())
        body = merged.read_text(encoding="utf-16")
        self.assertIn("/* alpha */", body)
        self.assertIn("/* beta */", body)


class ConflictRegexTests(unittest.TestCase):
    """The user implements ``_resolve_conflicts_pick_later`` — we at least
    verify the regex pattern itself matches a real diff3 ``-m`` block."""

    SAMPLE = (
        "before\n"
        "<<<<<<< running\n"
        "from running\n"
        "||||||| vanilla\n"
        "from vanilla\n"
        "=======\n"
        "from mod\n"
        ">>>>>>> mod\n"
        "after\n"
    )

    def test_regex_captures_three_sides(self) -> None:
        m = _CONFLICT_RE.search(self.SAMPLE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("ours"), "from running\n")
        self.assertEqual(m.group("base"), "from vanilla\n")
        self.assertEqual(m.group("theirs"), "from mod\n")

    def test_resolve_picks_theirs_when_implemented(self) -> None:
        try:
            out = _resolve_conflicts_pick_later(self.SAMPLE)
        except NotImplementedError:
            self.skipTest("user hasn't implemented _resolve_conflicts_pick_later yet")
        # When implemented correctly, only "from mod" should remain.
        self.assertNotIn("<<<<<<<", out)
        self.assertNotIn(">>>>>>>", out)
        self.assertNotIn("from running", out)
        self.assertNotIn("from vanilla", out)
        self.assertIn("from mod", out)
        self.assertIn("before", out)
        self.assertIn("after", out)


if __name__ == "__main__":
    unittest.main()
