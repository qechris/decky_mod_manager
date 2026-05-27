"""Tests for the appmanifest_*.acf parser.

The previous implementation used one regex with .*? and re.DOTALL spanning
three fields. That coupled to field order and could in principle false-match
if a name contained the literal text "installdir". These tests pin down the
new behavior — three independent per-field regexes — against realistic and
adversarial input.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from mod_manager import _parse_appmanifest  # noqa: E402


REAL_W3_MANIFEST = """"AppState"
{
\t"appid"\t\t"292030"
\t"Universe"\t\t"1"
\t"name"\t\t"The Witcher 3: Wild Hunt"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"The Witcher 3"
\t"LastUpdated"\t\t"1701234567"
\t"SizeOnDisk"\t\t"55000000000"
}
"""


class AppmanifestParseTests(unittest.TestCase):
    def test_parses_real_witcher_3_manifest(self) -> None:
        fields = _parse_appmanifest(REAL_W3_MANIFEST)
        self.assertEqual(fields, {
            "appid": "292030",
            "name": "The Witcher 3: Wild Hunt",
            "installdir": "The Witcher 3",
        })

    def test_field_order_does_not_matter(self) -> None:
        scrambled = """"AppState"
{
\t"installdir"\t\t"some-game-dir"
\t"name"\t\t"Some Game"
\t"appid"\t\t"123456"
}
"""
        fields = _parse_appmanifest(scrambled)
        self.assertEqual(fields["appid"], "123456")
        self.assertEqual(fields["name"], "Some Game")
        self.assertEqual(fields["installdir"], "some-game-dir")

    def test_name_containing_literal_installdir_does_not_false_match(self) -> None:
        # The old regex's `.*?"installdir"` would prematurely terminate on a
        # name like this. With per-field regexes, each field is parsed
        # independently — no cross-field interference.
        adversarial = """"AppState"
{
\t"appid"\t\t"999"
\t"name"\t\t"Bug: a game named installdir"
\t"installdir"\t\t"actual-dir"
}
"""
        fields = _parse_appmanifest(adversarial)
        self.assertEqual(fields["name"], "Bug: a game named installdir")
        self.assertEqual(fields["installdir"], "actual-dir")

    def test_missing_required_field_returns_none(self) -> None:
        incomplete = """"AppState"
{
\t"appid"\t\t"123"
\t"name"\t\t"only two fields"
}
"""
        self.assertIsNone(_parse_appmanifest(incomplete))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_parse_appmanifest(""))


if __name__ == "__main__":
    unittest.main()
