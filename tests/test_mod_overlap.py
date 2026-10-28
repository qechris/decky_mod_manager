"""Two mods that ship the same file must not break each other on disable."""

from __future__ import annotations

import asyncio
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from mod_manager import Game, ModManager  # noqa: E402


class OverlapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        root = Path(self._td.name)
        self.install = root / "game"
        (self.install / "data").mkdir(parents=True)
        (self.install / "data" / "x.txt").write_text("vanilla")
        self.game = Game(id="1", name="Game", install_path=str(self.install))
        self.mm = ModManager(root / "mm")
        self.a = self._install(root, "a")
        self.b = self._install(root, "b")

    def tearDown(self) -> None:
        self._td.cleanup()

    def _install(self, root: Path, name: str) -> str:
        archive = root / f"{name}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("data/x.txt", name)
        return asyncio.run(self.mm.install_archive(self.game, str(archive))).id

    def _x(self) -> str:
        return (self.install / "data" / "x.txt").read_text()

    def test_disable_first_then_second(self) -> None:
        self.mm.enable_mod(self.game, self.a)
        self.mm.enable_mod(self.game, self.b)
        self.assertEqual(self._x(), "b")
        self.mm.disable_mod(self.game, self.a)
        self.assertEqual(self._x(), "b")
        self.mm.disable_mod(self.game, self.b)
        self.assertEqual(self._x(), "vanilla")

    def test_disable_second_then_first(self) -> None:
        self.mm.enable_mod(self.game, self.a)
        self.mm.enable_mod(self.game, self.b)
        self.mm.disable_mod(self.game, self.b)
        self.assertEqual(self._x(), "a")
        self.mm.disable_mod(self.game, self.a)
        self.assertEqual(self._x(), "vanilla")

    def test_uninstall_restores_vanilla(self) -> None:
        self.mm.enable_mod(self.game, self.a)
        self.mm.enable_mod(self.game, self.b)
        self.mm.uninstall_mod(self.game, self.a)
        self.mm.uninstall_mod(self.game, self.b)
        self.assertEqual(self._x(), "vanilla")

    def test_failed_extract_leaves_nothing(self) -> None:
        bad = Path(self._td.name) / "bad.zip"
        bad.write_text("not a zip")
        with self.assertRaises(Exception):
            asyncio.run(self.mm.install_archive(self.game, str(bad)))
        self.assertEqual(len(list((self.mm.library_dir / "1").iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
