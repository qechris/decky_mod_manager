"""Tests for the URL path re-encoder used before urllib download.

Production failure: Nexus's CDN returns download URLs with raw spaces in
the filename portion (e.g. ``/cdn/952/7198/AutoLoot All-in-One NG.zip``).
Python's urllib refuses these with::

    Exception: URL can't contain control characters. '/cdn/.../AutoLoot
    All-in-One NG Update_…zip?…' (found at least ' ')

These tests pin down the encoder's behaviour so we don't regress.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from nexus import _percent_encode_path  # noqa: E402


class PercentEncodePathTests(unittest.TestCase):
    def test_spaces_in_path_become_percent_20(self) -> None:
        # Real-world Nexus CDN URL shape, simplified.
        url = ("https://cdn.example.com/cdn/952/7198/"
               "AutoLoot All-in-One NG Update_4_4_1.zip?md5=abc&expires=123")
        out = _percent_encode_path(url)
        self.assertIn("AutoLoot%20All-in-One%20NG%20Update_4_4_1.zip", out)
        # Query string preserved verbatim
        self.assertIn("?md5=abc&expires=123", out)
        # Host preserved
        self.assertIn("cdn.example.com", out)

    def test_already_encoded_paths_are_not_double_encoded(self) -> None:
        url = "https://example.com/path/already%20escaped.zip"
        out = _percent_encode_path(url)
        # Must NOT become %2520 (double-encoded)
        self.assertEqual(out, "https://example.com/path/already%20escaped.zip")

    def test_no_spaces_unchanged(self) -> None:
        url = "https://example.com/clean/path/file.zip?q=1"
        self.assertEqual(_percent_encode_path(url), url)

    def test_unicode_in_path_encoded(self) -> None:
        url = "https://example.com/files/résumé.pdf"
        out = _percent_encode_path(url)
        # accented chars get UTF-8 percent encoded
        self.assertIn("r%C3%A9sum%C3%A9.pdf", out)

    def test_preserves_https_scheme_and_port(self) -> None:
        url = "https://cdn.example.com:8443/space here/file.zip"
        out = _percent_encode_path(url)
        self.assertTrue(out.startswith("https://cdn.example.com:8443/"))
        self.assertIn("space%20here", out)


if __name__ == "__main__":
    unittest.main()
