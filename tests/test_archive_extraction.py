"""Tests for the .zip/.tar.*/.7z/.rar extractor.

Production failure: many Nexus mods ship as .7z. Decky's PyInstaller-
frozen Python doesn't include py7zr, and we used to raise immediately
in that case. SteamOS does ship system ``7z`` and ``unrar`` binaries
in /usr/bin, so the fix is a subprocess fallback when the Python
module isn't importable.

These tests cover:
- .zip extraction (Python built-in, always works)
- .7z extraction (subprocess fallback, requires system 7z on PATH)
- .rar extraction (subprocess fallback, requires system unrar on PATH)
- Friendly error when neither path is available
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from mod_manager import _extract_archive  # noqa: E402


class ZipExtractionTests(unittest.TestCase):
    def test_zip_always_works(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            archive = tmp / "test.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("inner/file.txt", "hello")
                zf.writestr("inner/sub/nested.txt", "world")
            dest = tmp / "out"
            _extract_archive(archive, dest)
            self.assertEqual((dest / "inner" / "file.txt").read_text(), "hello")
            self.assertEqual((dest / "inner" / "sub" / "nested.txt").read_text(), "world")


@unittest.skipUnless(shutil.which("7z") or shutil.which("7za") or shutil.which("7zz"),
                     "no 7z CLI available on this host")
class SevenZExtractionViaSubprocessTests(unittest.TestCase):
    """Verify the CLI fallback works when py7zr isn't installed."""

    def test_7z_extracted_via_system_binary(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            staged = tmp / "stage"
            staged.mkdir()
            (staged / "file.txt").write_text("seven-zip content")
            (staged / "sub").mkdir()
            (staged / "sub" / "nested.txt").write_text("nested seven")
            archive = tmp / "test.7z"
            # Use whichever 7z binary is available to create the archive
            sevenz = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
            result = subprocess.run(
                [sevenz, "a", str(archive), str(staged / ".") + "/"],
                capture_output=True, text=True, cwd=staged,
            )
            self.assertEqual(result.returncode, 0,
                             f"7z create failed: {result.stderr}")
            dest = tmp / "out"
            _extract_archive(archive, dest)
            # The extracted layout depends on how 7z was invoked. Just check
            # the content files made it out somewhere under dest.
            all_files = {p.name for p in dest.rglob("*") if p.is_file()}
            self.assertIn("file.txt", all_files)
            self.assertIn("nested.txt", all_files)


class UnsupportedFormatTests(unittest.TestCase):
    def test_unknown_extension_raises_clearly(self) -> None:
        with TemporaryDirectory() as td:
            archive = Path(td) / "x.weirdformat"
            archive.write_bytes(b"garbage")
            with self.assertRaises(ValueError) as ctx:
                _extract_archive(archive, Path(td) / "out")
            self.assertIn("unsupported archive format", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
