"""DOMAIN.md indexing and Clearwater lookups."""

from __future__ import annotations

import unittest

from project import domain


class DomainTests(unittest.TestCase):
    def test_sections_by_heading(self):
        sizes = domain.get_domain_section("Sizes")
        self.assertIn("parentheses", sizes.casefold())
        self.assertIn("square brackets", sizes.casefold())
        sections = domain.inject("Sections of a pattern", "Abbreviations")
        self.assertIn("glossary", sections.casefold())
        self.assertIn(domain.GLOSSARY_WINS.split(".")[0], domain.GLOSSARY_WINS)

    def test_abbreviation_lookup(self):
        self.assertIsNotNone(domain.lookup_abbreviation("RC"))
        self.assertIn("row", domain.lookup_abbreviation("RC").casefold())
        found = domain.abbreviations_in_text("Set RC to 0. COL. MC in feeder.")
        tokens = {abbr.casefold() for abbr, _expansion in found}
        self.assertTrue({"rc", "col", "mc"} & tokens)

    def test_stitch_symbols_load(self):
        text = domain.stitch_symbols()
        self.assertGreater(len(text), 100)


if __name__ == "__main__":
    unittest.main()
