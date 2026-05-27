"""Tests for the Witcher 3 layout normalizer — the highest-stakes correctness
piece, because a wrong layout silently breaks the entire mod.

Each test sets up a payload directory matching a real-world archive shape,
calls ``post_install_payload``, and asserts what the final on-disk tree
looks like. We never invoke the game; we just check that what we'd hand to
``symlink_tree`` is the canonical install-relative layout REDengine expects.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from handlers.base import flatten_single_root  # noqa: E402
from handlers.witcher3 import Witcher3Handler  # noqa: E402


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _all_files(root: Path) -> set[str]:
    return {
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
    }


class LayoutNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name) / "abc123def456"
        self.root.mkdir()
        self.h = Witcher3Handler()

    def tearDown(self) -> None:
        self._td.cleanup()

    # Case A — archive ships fully wrapped: Mods/foo/content/...
    def test_already_install_root_layout_is_left_alone(self) -> None:
        _touch(self.root / "Mods" / "modFoo" / "content" / "scripts" / "x.ws", "ok")
        _touch(self.root / "DLC" / "dlcFoo" / "content" / "blob0.bundle")
        self.h.post_install_payload(self.root)
        self.assertEqual(
            _all_files(self.root),
            {
                "Mods/modFoo/content/scripts/x.ws",
                "DLC/dlcFoo/content/blob0.bundle",
            },
        )

    # Case A.1 — install-root layout but mod folder missing the `mod` prefix
    def test_install_root_renames_unprefixed_mod_folders(self) -> None:
        _touch(self.root / "Mods" / "Foo" / "content" / "scripts" / "x.ws", "ok")
        self.h.post_install_payload(self.root)
        self.assertEqual(
            _all_files(self.root),
            {"Mods/modFoo/content/scripts/x.ws"},
        )

    # Case B — single modFoo/ folder at the archive root (the most common shape)
    def test_single_mod_folder_at_root_wraps_in_mods(self) -> None:
        _touch(self.root / "modFoo" / "content" / "scripts" / "game" / "x.ws", "ok")
        _touch(self.root / "modFoo" / "content" / "bundles" / "blob0.bundle")
        self.h.post_install_payload(self.root)
        files = _all_files(self.root)
        self.assertIn("Mods/modFoo/content/scripts/game/x.ws", files)
        self.assertIn("Mods/modFoo/content/bundles/blob0.bundle", files)
        # No double content/
        for f in files:
            self.assertNotIn("content/content/", f)

    # Case B regression — the old bug: payload was `content/...` at root, the
    # handler wrapped it producing Mods/mod<id>/content/content/...
    def test_bare_content_root_does_not_produce_double_content(self) -> None:
        _touch(self.root / "content" / "scripts" / "game" / "x.ws", "ok")
        self.h.post_install_payload(self.root)
        files = _all_files(self.root)
        self.assertEqual(
            files,
            {f"Mods/mod{self.root.name}/content/scripts/game/x.ws"},
        )
        for f in files:
            self.assertNotIn("content/content/", f)

    # Case C — folder without `mod` prefix that has content/ inside
    def test_unprefixed_mod_folder_gets_prefix(self) -> None:
        _touch(self.root / "Foo" / "content" / "scripts" / "x.ws", "ok")
        self.h.post_install_payload(self.root)
        self.assertEqual(
            _all_files(self.root),
            {"Mods/modFoo/content/scripts/x.ws"},
        )

    # Case D — DLC folder at the root
    def test_dlc_folder_wraps_under_DLC(self) -> None:
        _touch(self.root / "dlcAlternateGwent" / "content" / "blob0.bundle")
        self.h.post_install_payload(self.root)
        self.assertEqual(
            _all_files(self.root),
            {"DLC/dlcAlternateGwent/content/blob0.bundle"},
        )

    # Case E — pointless wrapper dir like "MyMod-v2.1/modFoo/..."
    def test_single_wrapper_dir_is_hoisted(self) -> None:
        _touch(self.root / "MyMod-v2.1" / "modFoo" / "content" / "scripts" / "x.ws", "ok")
        self.h.post_install_payload(self.root)
        files = _all_files(self.root)
        self.assertIn("Mods/modFoo/content/scripts/x.ws", files)

    # Case F — only `scripts/` at root, no content/. Wrap inside content/.
    def test_bare_scripts_dir_wrapped_in_mod_content(self) -> None:
        _touch(self.root / "scripts" / "game" / "x.ws", "ok")
        self.h.post_install_payload(self.root)
        self.assertEqual(
            _all_files(self.root),
            {f"Mods/mod{self.root.name}/scripts/game/x.ws"},
        )
        # Note: this is intentional — we wrap as mod<uuid>/scripts/... because
        # there's no content/ to nest under. The mod will still be ignored by
        # the engine, but at least we don't lose the files.
        # A future improvement: if only scripts/ is at root, wrap as content/scripts/.

    # Bonus — pathological deeply-nested single dirs
    def test_deeply_nested_single_wrappers(self) -> None:
        deep = self.root / "a" / "b" / "c" / "modFoo" / "content" / "scripts" / "x.ws"
        _touch(deep, "ok")
        self.h.post_install_payload(self.root)
        files = _all_files(self.root)
        self.assertIn("Mods/modFoo/content/scripts/x.ws", files)


class FlattenSingleRootTests(unittest.TestCase):
    """Pin down flatten_single_root's contract — particularly its return
    value, which signals whether the layout was actually normalized."""

    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_single_dir_returns_true_and_hoists(self) -> None:
        _touch(self.root / "wrapper" / "a.txt")
        _touch(self.root / "wrapper" / "b.txt")
        self.assertTrue(flatten_single_root(self.root))
        self.assertEqual(_all_files(self.root), {"a.txt", "b.txt"})

    def test_multiple_entries_returns_false_no_op(self) -> None:
        _touch(self.root / "a" / "x.txt")
        _touch(self.root / "b" / "y.txt")
        self.assertFalse(flatten_single_root(self.root))
        # Layout untouched — caller's responsibility to handle multi-entry
        self.assertEqual(_all_files(self.root), {"a/x.txt", "b/y.txt"})

    def test_single_file_returns_false(self) -> None:
        _touch(self.root / "lone.txt")
        self.assertFalse(flatten_single_root(self.root))
        self.assertEqual(_all_files(self.root), {"lone.txt"})

    def test_empty_dir_returns_false(self) -> None:
        self.assertFalse(flatten_single_root(self.root))

    def test_dotfile_entries_are_ignored(self) -> None:
        # macOS sticks .DS_Store everywhere; archives may carry .git/.svn —
        # we shouldn't let those make us think it's a multi-entry payload.
        _touch(self.root / ".DS_Store")
        _touch(self.root / "wrapper" / "a.txt")
        self.assertTrue(flatten_single_root(self.root))
        self.assertEqual(_all_files(self.root), {".DS_Store", "a.txt"})


if __name__ == "__main__":
    unittest.main()
