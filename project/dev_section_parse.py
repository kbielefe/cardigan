"""Development check for the section-parse prompt.

Not part of the regression suite. Run it by name:

    uv run python -m unittest project.dev_section_parse

Reads the canned sections written by ``project.dev_section_split``.
"""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from project.complete import complete
from project.model import SECTION_KINDS
from project.stages.section_parse import SCHEMA, SYSTEM

SPLIT_DUMP = Path("/tmp/cardigan-section-split.json")
PARSE_DUMP = Path("/tmp/cardigan-section-parse.json")
POOL = 6

# Judged by hand against the canned split. The check prints disagreements; it does not fail on them.
EXPECTED: dict[str, list[dict]] = {
    "city-farmhouse-wrap-sweater-scarf.html": [
        {"kind": "notes", "procedure": False},
        {"kind": "page", "procedure": False},
        {"kind": "yarn", "procedure": False},
        {"kind": "machine", "procedure": False},
        {"kind": "gauge", "procedure": False},
        {"kind": "sizes", "procedure": False, "size_names": ["XS-M", "L-2X", "3X-5X"]},
        {"kind": "glossary", "procedure": False},
        {"kind": "notes", "procedure": False},
        {"kind": "piece", "procedure": True, "copies": None, "heading": "Body"},
        {"kind": "piece", "procedure": True, "copies": 2, "heading": "Sleeve (make 2)"},
        {"kind": "finishing", "procedure": False},
        {"kind": "finishing", "procedure": False},
        {"kind": "page", "procedure": False},
    ],
    "creative-tien-lk150-tuck-blanket.html": [
        {"kind": "notes", "procedure": False},
        {"kind": "notes", "procedure": False},
        {"kind": "method", "procedure": True},
        {"kind": "notes", "procedure": False},
        {"kind": "method", "procedure": True},
        {"kind": "page", "procedure": False},
    ],
    "clearwater-lk150-fairisle-method-1.html": [
        {"kind": "method", "procedure": False},
        {"kind": "method", "procedure": True},
        {"kind": "page", "procedure": False},
    ],
    "city-farmhouse-simple-stitch-sweater.html": [
        {"kind": "notes", "procedure": False},
        {"kind": "page", "procedure": False},
        {"kind": "yarn", "procedure": False},
        {"kind": "machine", "procedure": False},
        {"kind": "gauge", "procedure": False},
        {
            "kind": "sizes",
            "procedure": False,
            "size_names": ["XS", "S", "M", "L", "XL", "2X", "3X", "4X", "5X"],
        },
        {"kind": "page", "procedure": False},
        {"kind": "glossary", "procedure": False},
        {"kind": "piece", "procedure": True, "copies": None, "heading": "Front"},
        {"kind": "piece", "procedure": True, "copies": None, "heading": "Back"},
        {"kind": "piece", "procedure": True, "copies": 2, "heading": "Sleeve"},
        {"kind": "finishing", "procedure": False},
        {"kind": "page", "procedure": False},
    ],
}


def _load_split() -> list[dict]:
    if not SPLIT_DUMP.is_file():
        raise AssertionError(f"missing {SPLIT_DUMP}; run project.dev_section_split first")
    data = json.loads(SPLIT_DUMP.read_text(encoding="utf-8"))
    if type(data) is not list or not data:
        raise AssertionError("section split dump is empty")
    return data


def _parse(section: str) -> dict:
    payload = complete(
        section,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="section",
    )
    kind = payload.get("kind")
    if kind not in SECTION_KINDS:
        raise AssertionError(f"kind {kind!r}")
    if payload.get("heading") is not None and type(payload.get("heading")) is not str:
        raise AssertionError("heading")
    copies = payload.get("copies")
    if copies is not None and type(copies) is not int:
        raise AssertionError("copies")
    if type(payload.get("procedure")) is not bool:
        raise AssertionError("procedure")
    names = payload.get("size_names")
    if type(names) is not list or any(type(name) is not str for name in names):
        raise AssertionError("size_names")
    glossary = payload.get("glossary")
    if type(glossary) is not list:
        raise AssertionError("glossary")
    for entry in glossary:
        if type(entry) is not dict:
            raise AssertionError("glossary entry")
        if type(entry.get("abbr")) is not str or type(entry.get("expansion")) is not str:
            raise AssertionError("glossary entry")
    return payload


def _first_line(section: str) -> str:
    line = section.strip().splitlines()[0] if section.strip() else ""
    return line[:80]


class SectionParseDevTests(unittest.TestCase):
    def test_canned_sections(self) -> None:
        patterns = _load_split()
        jobs: list[tuple[int, int, str]] = []
        for pattern_index, item in enumerate(patterns):
            sections = item.get("sections")
            if type(sections) is not list or not sections:
                self.fail(f"no sections in {item.get('pattern')}")
            for section_index, section in enumerate(sections):
                jobs.append((pattern_index, section_index, section))

        parsed: dict[tuple[int, int], dict] = {}
        with ThreadPoolExecutor(max_workers=POOL) as pool:
            futures = {
                (pattern_index, section_index): pool.submit(_parse, section)
                for pattern_index, section_index, section in jobs
            }
            for key, future in futures.items():
                parsed[key] = future.result()

        report = []
        for pattern_index, item in enumerate(patterns):
            name = Path(item["pattern"]).name
            expected = EXPECTED.get(name, [])
            rows = []
            for section_index, section in enumerate(item["sections"]):
                got = parsed[(pattern_index, section_index)]
                want = expected[section_index] if section_index < len(expected) else {}
                rows.append(
                    {
                        "index": section_index,
                        "first_line": _first_line(section),
                        "expected": want,
                        "parsed": got,
                    }
                )
            report.append({"pattern": item["pattern"], "sections": rows})

        PARSE_DUMP.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(PARSE_DUMP)

        for item in report:
            print(f"\n{item['pattern']}")
            for row in item["sections"]:
                got = row["parsed"]
                want = row["expected"]
                marks = []
                for field in ("kind", "procedure", "copies", "heading"):
                    if field in want and got.get(field) != want[field]:
                        marks.append(f"{field}: {got.get(field)!r} != {want[field]!r}")
                if "size_names" in want and got.get("size_names") != want["size_names"]:
                    marks.append(f"size_names: {got.get('size_names')!r}")
                flag = "  " if not marks else "! "
                extra = ""
                if got.get("glossary"):
                    extra = " glossary=" + ", ".join(
                        f"{entry['abbr']}={entry['expansion']}" for entry in got["glossary"]
                    )
                if got.get("size_names"):
                    extra += " sizes=" + ", ".join(got["size_names"])
                note = "" if not marks else "  [" + "; ".join(marks) + "]"
                print(
                    f"{flag}[{row['index']:02d}] {got.get('kind'):<10} proc={got.get('procedure')!s:<5} "
                    f"copies={got.get('copies')!s:<4} {row['first_line']!r}{extra}{note}"
                )


if __name__ == "__main__":
    unittest.main()
