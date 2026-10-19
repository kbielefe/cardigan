"""Development check for the section-split prompt.

Not part of the regression suite. Run it by name:

    uv run python -m unittest project.dev_section_split
"""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pattern_import.extract import extract_bytes
from project.complete import complete
from project.stages.split import SCHEMA, SYSTEM

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    "sources/patterns/city-farmhouse-wrap-sweater-scarf.html",
    "sources/patterns/creative-tien-lk150-tuck-blanket.html",
    "sources/patterns/clearwater-lk150-fairisle-method-1.html",
    "sources/patterns/city-farmhouse-simple-stitch-sweater.html",
)


def _reading(relative: str) -> str:
    path = ROOT / relative
    result = extract_bytes(path.read_bytes(), path.name, "text/html")
    if not result.ok:
        raise AssertionError(result.message)
    return result.reading


def _split(reading: str) -> list[str]:
    payload = complete(
        reading,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="sections",
    )
    sections = payload.get("sections")
    if type(sections) is not list or not sections:
        raise AssertionError(f"expected sections, got {type(sections).__name__}")
    if any(type(section) is not str or not section for section in sections):
        raise AssertionError("each section must be a non-empty string")
    return sections


class SectionSplitDevTests(unittest.TestCase):
    def test_canned_patterns(self) -> None:
        readings = {relative: _reading(relative) for relative in PATTERNS}
        with ThreadPoolExecutor(max_workers=len(PATTERNS)) as pool:
            futures = {relative: pool.submit(_split, readings[relative]) for relative in PATTERNS}
            splits = {relative: future.result() for relative, future in futures.items()}

        report = [
            {"pattern": relative, "reading": readings[relative], "sections": splits[relative]}
            for relative in PATTERNS
        ]
        out = Path("/tmp/cardigan-section-split.json")
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(out)

        for item in report:
            reading = item["reading"]
            sections = item["sections"]
            cursor = 0
            for section in sections:
                at = reading.find(section, cursor)
                self.assertGreaterEqual(at, cursor, item["pattern"])
                cursor = at + len(section)
            self.assertEqual("".join(sections), reading, item["pattern"])


if __name__ == "__main__":
    unittest.main()
