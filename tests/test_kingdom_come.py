"""Tests for the Kingdom Come: Deliverance handler.

KCD mods live at ``<install>/Mods/<mod_name>/`` with a typical inner
shape of ``Data/*.pak`` (+ optional ``mod.manifest``, ``mod.cfg``,
``Localization/*.pak``). Optional ``Mods/mod_order.txt`` acts as both a
load-order spec and a whitelist when present.

Critical contract these tests pin down:

- Layout normalizer handles the 4 common archive shapes (wrapped,
  single-mod-folder, bare contents, wrapper-dir).
- ``mod_order.txt`` is appended to ONLY when it already exists — we never
  create one ourselves, because doing so would silently demote the user's
  other unlisted mods to "not loaded".
- ``mod_order.txt`` comment lines (``#``) and inline comments are preserved
  by removal logic.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from handlers.kingdom_come import (  # noqa: E402
    KCD_APPID,
    KCD2_APPID,
    KingdomComeHandler,
    _ensure_mod_order_entries,
    _remove_mod_order_entries,
)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _all_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


@dataclass
class FakeGame:
    id: str
    install_path: str


# ---------------------------------------------------------------- layout


class LayoutNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name) / "abc123def456"
        self.root.mkdir()
        self.h = KingdomComeHandler()

    def tearDown(self) -> None:
        self._td.cleanup()

    # Case A — archive already wrapped: Mods/foo/Data/...
    def test_already_install_root_layout_left_alone(self) -> None:
        _touch(self.root / "Mods" / "MyMod" / "Data" / "mod.pak", "x")
        _touch(self.root / "Mods" / "MyMod" / "mod.manifest", "<x/>")
        self.h.post_install_payload(self.root)
        self.assertEqual(_all_files(self.root), {
            "Mods/MyMod/Data/mod.pak",
            "Mods/MyMod/mod.manifest",
        })

    # Case B — single mod folder at archive root (most common Nexus shape)
    def test_single_mod_folder_wrapped_in_mods(self) -> None:
        _touch(self.root / "MyMod" / "Data" / "mod.pak", "x")
        _touch(self.root / "MyMod" / "mod.manifest", "<x/>")
        self.h.post_install_payload(self.root)
        self.assertEqual(_all_files(self.root), {
            "Mods/MyMod/Data/mod.pak",
            "Mods/MyMod/mod.manifest",
        })

    # Case C — bare contents (Data/, mod.manifest) at archive root
    def test_bare_contents_wrapped_in_mod_uuid_folder(self) -> None:
        _touch(self.root / "Data" / "mod.pak", "x")
        _touch(self.root / "mod.manifest", "<x/>")
        self.h.post_install_payload(self.root)
        # Wrapped under Mods/<root-folder-name>/
        self.assertEqual(_all_files(self.root), {
            f"Mods/{self.root.name}/Data/mod.pak",
            f"Mods/{self.root.name}/mod.manifest",
        })

    # Case D — pointless wrapper dir (Vortex etc) above the real layout
    def test_wrapper_dir_hoisted_first(self) -> None:
        _touch(self.root / "MyMod-v1.2-Nexus" / "MyMod" / "Data" / "mod.pak", "x")
        self.h.post_install_payload(self.root)
        files = _all_files(self.root)
        self.assertIn("Mods/MyMod/Data/mod.pak", files)

    # Bonus — two mod folders at the root
    def test_multiple_mod_folders_at_root(self) -> None:
        _touch(self.root / "ModA" / "Data" / "a.pak", "a")
        _touch(self.root / "ModB" / "Data" / "b.pak", "b")
        self.h.post_install_payload(self.root)
        self.assertEqual(_all_files(self.root), {
            "Mods/ModA/Data/a.pak",
            "Mods/ModB/Data/b.pak",
        })

    # Localization-only mod (no Data/)
    def test_localization_only_mod_is_recognised(self) -> None:
        _touch(self.root / "MyLocalisedMod" / "Localization" / "english_xml.pak", "x")
        self.h.post_install_payload(self.root)
        self.assertEqual(_all_files(self.root), {
            "Mods/MyLocalisedMod/Localization/english_xml.pak",
        })


# ---------------------------------------------------------------- mod_order


class ModOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.path = Path(self._td.name) / "mod_order.txt"

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_ensure_does_nothing_when_file_absent(self) -> None:
        # Critical: we MUST NOT create a partial whitelist. Existing mods
        # outside our state would get demoted to "not loaded".
        _ensure_mod_order_entries(self.path, ["ModA", "ModB"])
        self.assertFalse(self.path.exists())

    def test_ensure_appends_when_file_present(self) -> None:
        self.path.write_text("ExistingMod\n")
        _ensure_mod_order_entries(self.path, ["NewMod"])
        self.assertEqual(self.path.read_text().splitlines(),
                         ["ExistingMod", "NewMod"])

    def test_ensure_does_not_duplicate(self) -> None:
        self.path.write_text("ModA\nModB\n")
        _ensure_mod_order_entries(self.path, ["ModB", "ModC"])
        self.assertEqual(self.path.read_text().splitlines(),
                         ["ModA", "ModB", "ModC"])

    def test_ensure_treats_commented_lines_as_inactive(self) -> None:
        self.path.write_text("# ModA\nModB\n")
        _ensure_mod_order_entries(self.path, ["ModA"])
        # Should re-add ModA even though it's commented out (the user
        # disabled it via comment, but we're re-enabling explicitly)
        lines = self.path.read_text().splitlines()
        self.assertIn("ModA", lines)
        # Original comment line preserved (we just append; we don't rewrite
        # the comment)
        self.assertIn("# ModA", lines)

    def test_remove_keeps_comments(self) -> None:
        self.path.write_text("# leave me alone\nModA\nModB\n")
        _remove_mod_order_entries(self.path, ["ModA"])
        self.assertEqual(self.path.read_text().splitlines(),
                         ["# leave me alone", "ModB"])

    def test_remove_strips_inline_comments_when_matching(self) -> None:
        self.path.write_text("ModA   # the troublesome one\nModB\n")
        _remove_mod_order_entries(self.path, ["ModA"])
        self.assertEqual(self.path.read_text().splitlines(), ["ModB"])

    def test_remove_when_absent_is_noop(self) -> None:
        _remove_mod_order_entries(self.path, ["ModA"])  # no exception


# ---------------------------------------------------------------- registry


class RegistryTests(unittest.TestCase):
    def test_both_kcd_appids_route_to_handler(self) -> None:
        from handlers import get_handler
        self.assertIsInstance(get_handler(KCD_APPID), KingdomComeHandler)
        self.assertIsInstance(get_handler(KCD2_APPID), KingdomComeHandler)
        # Wrong appid should fall through to generic
        from handlers.generic import GenericHandler
        self.assertIsInstance(get_handler("999999"), GenericHandler)


if __name__ == "__main__":
    unittest.main()
