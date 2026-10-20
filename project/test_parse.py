"""Accept runs the staged parse pipeline and stores the project."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from pattern_import.extract import extract_bytes
from pattern_import.server import make_server
from project.complete import complete, pass_schema, read_key, schema
from project.parse import ParseFailure, build_size_passes, parse_reading
from project.store import connect, load_project

ROOT = Path(__file__).resolve().parents[1]
WRAP = ROOT / "sources/patterns/city-farmhouse-wrap-sweater-scarf.html"
SIZES = ("XS-M", "L-2X", "3X-5X")


def _reading() -> str:
    result = extract_bytes(WRAP.read_bytes(), WRAP.name, "text/html")
    if not result.ok:
        raise AssertionError(result.message)
    return result.reading


def _line(reading: str, start: str) -> str:
    at = reading.index(start)
    end = reading.find("\n", at)
    return reading[at:end].strip()


def _method(procedure: bool) -> dict:
    return {
        "kind": "method",
        "heading": None,
        "copies": None,
        "procedure": procedure,
        "size_names": [],
        "glossary": [],
    }


def _pass(kind: str, cite: str, count: int = 1, **extra) -> dict:
    body = {
        "kind": kind,
        "count": count,
        "cite": cite,
        "carriage_end": None,
        "row_counter": None,
        "open_point": None,
        "mark": None,
        "selections": [],
        "settings": [],
        "shapes": [],
        "yarns": [],
    }
    body.update(extra)
    return body


def _wrap_payload(reading: str) -> dict:
    body_cast = _line(reading, "ewrap cast on (53, 61, 69)")
    sleeve_cast = _line(reading, "ewrap cast on (32, 34, 38)")
    knit_two = "Knit 2 rows."
    rib = _line(reading, "K (6, 6, 6) rows")
    body_setup = _pass(
        "setup",
        body_cast,
        row_counter={"kind": "reset", "value": 0},
        open_point="extra_needle_side",
        selections=[
            {"role": "working", "method": "each_side", "count": 26},
            {"role": "working", "method": "extra", "count": 1},
        ],
        shapes=[{"name": "cast_on", "count": 53, "technique": "e-wrap"}],
    )
    sleeve_setup = _pass(
        "setup",
        sleeve_cast,
        row_counter={"kind": "reset", "value": 0},
        selections=[{"role": "working", "method": "each_side", "count": 16}],
        shapes=[{"name": "cast_on", "count": 32, "technique": "e-wrap"}],
    )

    def sizes(setup: dict, trip: dict) -> list[dict]:
        return [{"name": name, "passes": [setup, trip], "repeats": []} for name in SIZES]

    return {
        "pieces": [
            {
                "name": "Body",
                "copies": 1,
                "parsed": True,
                "sizes": sizes(body_setup, _pass("trip", knit_two, count=2)),
            },
            {
                "name": "Sleeve",
                "copies": 2,
                "parsed": True,
                "sizes": sizes(sleeve_setup, _pass("trip", rib, count=6)),
            },
            {"name": "How to Wrap", "copies": 1, "parsed": False, "sizes": []},
        ]
    }


def _section_reading(content: str) -> dict:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    first = lines[0] if lines else None
    blank = {"copies": None, "procedure": False, "size_names": [], "glossary": []}
    if first and first.startswith("Glossary"):
        return {
            "kind": "glossary",
            "heading": "Glossary",
            "copies": None,
            "procedure": False,
            "size_names": [],
            "glossary": [{"abbr": "RC", "expansion": "row count"}],
        }
    if first and first.startswith("Size"):
        return {**blank, "kind": "sizes", "heading": "Size:", "size_names": ["XS-M", "L-2X", "3X-5X"]}
    if first and first.startswith("Gauge"):
        return {**blank, "kind": "gauge", "heading": "Gauge"}
    if first and (first.startswith("How to Wrap") or first.startswith("Sew ")):
        return {**blank, "kind": "finishing", "heading": first}
    if content.lstrip().startswith("Body"):
        return {**blank, "kind": "piece", "heading": "Body", "procedure": True}
    if first and first.startswith("Sleeve"):
        copies = 2 if "make 2" in content.casefold() or "second sleeve" in content.casefold() else None
        return {**blank, "kind": "piece", "heading": first, "copies": copies, "procedure": True}
    return {**blank, "kind": "notes", "heading": first}


def _section_passes(content: str, pieces: list[dict]) -> dict:
    count = 1
    for line in content.splitlines():
        if line.startswith("Size count: "):
            count = int(line.split(": ", 1)[1])
            break
    usable: list[dict] = []
    for piece in pieces:
        if not piece["parsed"] or f"Heading: {piece['name']}\n" not in content:
            continue
        for size in piece["sizes"]:
            kept = [step for step in size["passes"] if step["cite"] in content]
            if kept:
                usable.append({"name": size["name"], "passes": kept, "repeats": []})
        break
    if not usable:
        cite = "Knit 2 rows." if "Knit 2 rows." in content else content.strip().splitlines()[-1]
        usable = [{"name": "one", "passes": [_pass("trip", cite)], "repeats": []}]
    if len(usable) < count:
        usable = [usable[0] for _ in range(count)]
    return {"sizes": usable[:count]}


def _stage_complete(reading: str, wrap: dict, *, fail_at: str | None = None):
    pieces = wrap["pieces"]

    def respond(
        content,
        *,
        schema,
        system,
        reasoning_effort="medium",
        schema_name="result",
        on_delta=None,
        **_extra,
    ):
        if fail_at is not None and schema_name == fail_at:
            raise ParseFailure("The model did not answer.")
        if schema_name == "metadata":
            return {"name": "Wrap Sweater Scarf"}
        if schema_name == "sections":
            marker = "\nBody\n"
            if marker in content:
                at = content.index(marker)
                return {"sections": [content[:at], content[at:]]}
            return {"sections": [content]}
        if schema_name == "pieces":
            return {
                "pieces": [
                    {
                        "name": piece["name"],
                        "copies": piece["copies"],
                        "parsed": piece["parsed"],
                        "cite": piece["name"],
                    }
                    for piece in pieces
                ]
            }
        if schema_name == "vocabulary":
            return {"abbreviations": [{"abbr": "RC", "expansion": "row counter"}]}
        if schema_name == "sizes":
            for piece in pieces:
                if f"Piece: {piece['name']}" in content:
                    if not piece["parsed"]:
                        return {"sizes": []}
                    return {"sizes": [{"name": size["name"]} for size in piece["sizes"]]}
            return {"sizes": [{"name": "one"}]}
        if schema_name == "sections":
            for piece in pieces:
                if not piece["parsed"] or f"Piece: {piece['name']}" not in content:
                    continue
                for size in piece["sizes"]:
                    if f"Size: {size['name']}" in content:
                        return {"sections": [{"cite": step["cite"]} for step in size["passes"]]}
            return {"sections": [{"cite": "Knit 2 rows."}]}
        if schema_name == "passes":
            for piece in pieces:
                if not piece["parsed"] or f"Piece: {piece['name']}" not in content:
                    continue
                for size in piece["sizes"]:
                    if f"Size: {size['name']}" in content:
                        return {"passes": size["passes"], "repeats": size.get("repeats") or []}
            return {"passes": [], "repeats": []}
        if schema_name == "charts":
            return {"piece": "Body", "size": "XS-M", "passes": [], "repeats": []}
        if schema_name == "chart_passes":
            return {"passes": [], "repeats": []}
        if schema_name == "section":
            return _section_reading(content)
        if schema_name == "section_passes":
            return _section_passes(content, pieces)
        raise AssertionError(f"unexpected stage {schema_name}")

    return respond


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.reading = _reading()
        self.db = connect(":memory:")
        self.wrap = _wrap_payload(self.reading)

    def tearDown(self):
        self.db.close()

    def test_wrap_sweater_splits_into_sections(self):
        stored = parse_reading(self.reading, _stage_complete(self.reading, self.wrap), self.db)
        self.assertEqual(load_project(self.db, stored.id), stored)
        self.assertEqual(stored.name, "Wrap Sweater Scarf")
        self.assertEqual("".join(section.text for section in stored.sections), self.reading)
        self.assertGreaterEqual(len(stored.sections), 2)
        self.assertTrue(stored.sections[1].text.startswith("\nBody\n"))
        self.assertEqual(stored.sections[1].kind, "piece")
        self.assertEqual(stored.sections[1].heading, "Body")
        self.assertTrue(stored.sections[1].procedure)
        self.assertIsNone(stored.sections[1].copies)
        self.assertEqual(stored.sections[0].kind, "notes")
        self.assertEqual([piece.name for piece in stored.pieces], ["Body"])
        self.assertEqual(stored.pieces[0].copies, 1)
        self.assertEqual(len(stored.pieces[0].sizes), 1)
        self.assertGreaterEqual(len(stored.pieces[0].sizes[0].passes), 1)
        for size in stored.pieces[0].sizes:
            for step in size.passes:
                self.assertIn(stored.reading[step.cite_start : step.cite_end], stored.sections[1].text)

    def test_failed_call_after_bootstrap_leaves_the_project(self):
        with self.assertRaises(ParseFailure) as caught:
            parse_reading(
                self.reading,
                _stage_complete(self.reading, self.wrap, fail_at="sections"),
                self.db,
            )
        self.assertEqual(str(caught.exception), "The model did not answer.")
        self.assertEqual(self.db.execute("SELECT count(*) FROM project").fetchone()[0], 1)
        stored = load_project(self.db, 1)
        self.assertEqual(stored.name, "Wrap Sweater Scarf")
        self.assertEqual(stored.sections, ())

    def test_failed_call_before_answer_still_raises(self):
        with self.assertRaises(ParseFailure) as caught:
            parse_reading(self.reading, _crash, self.db)
        self.assertEqual(str(caught.exception), "The model did not answer.")

    def test_a_section_outside_the_reading_leaves_the_project(self):
        def respond(content, **_kwargs):
            if _kwargs.get("schema_name") == "metadata":
                return {"name": "Wrap"}
            return {"sections": ["this sentence is not in the reading"]}

        with self.assertRaises(ParseFailure):
            parse_reading(self.reading, respond, self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM project").fetchone()[0], 1)
        stored = load_project(self.db, 1)
        self.assertEqual(stored.sections, ())

    def test_dropped_blank_lines_stay_in_the_sections(self):
        reading = "Gauge:\n4 inches\n\nBody\nKnit 2 rows."

        def respond(content, **_kwargs):
            if _kwargs.get("schema_name") == "metadata":
                return {"name": "Gauge swatch"}
            if _kwargs.get("schema_name") == "section":
                return _section_reading(content)
            if _kwargs.get("schema_name") == "section_passes":
                return {"sizes": [{"name": "Body", "passes": [_pass("trip", "Knit 2 rows.", count=2)], "repeats": []}]}
            return {"sections": ["Gauge:\n4 inches", "Body\nKnit 2 rows."]}

        stored = parse_reading(reading, respond, self.db)
        self.assertEqual("".join(section.text for section in stored.sections), reading)
        self.assertEqual(stored.sections[0].text, "Gauge:\n4 inches\n\n")
        self.assertEqual(stored.sections[0].kind, "gauge")
        self.assertEqual(stored.sections[1].text, "Body\nKnit 2 rows.")
        self.assertEqual(stored.sections[1].kind, "piece")

    def test_every_piece_failing_stores_the_project_row(self):
        with self.assertRaises(ParseFailure):
            parse_reading("Knit 2 rows.", _stage_complete("Knit 2 rows.", self.wrap, fail_at="sections"), self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM project").fetchone()[0], 1)

    def test_an_unnamed_end_stays_open(self):
        passes, _repeats = build_size_passes(
            "Knit 2 rows.",
            {"passes": [_pass("trip", "Knit 2 rows.", count=2, carriage_end="left")], "repeats": []},
        )
        self.assertIsNone(passes[0].carriage_end)
        self.assertEqual(passes[0].open_point, "carriage_end")

    def test_an_unnamed_extra_needle_stays_open(self):
        quote = "1 additional needle in work"
        passes, _repeats = build_size_passes(
            quote + ".",
            {
                "passes": [
                    _pass(
                        "setup",
                        quote,
                        selections=[{"role": "working", "method": "extra", "count": 1, "side": "left"}],
                    )
                ],
                "repeats": [],
            },
        )
        self.assertEqual(passes[0].open_point, "extra_needle_side")
        self.assertIsNone(passes[0].selections[0].side)

    def test_sections_round_trip(self):
        stored = parse_reading(
            "How to Wrap:\nFold it.",
            _stage_complete("How to Wrap:\nFold it.", self.wrap),
            self.db,
        )
        self.assertEqual(load_project(self.db, stored.id), stored)
        section = stored.sections[0]
        self.assertEqual(section.text, "How to Wrap:\nFold it.")
        self.assertEqual(section.kind, "finishing")
        self.assertEqual(section.heading, "How to Wrap:")
        self.assertFalse(section.procedure)
        self.assertIsNone(section.copies)
        self.assertEqual(stored.pieces, ())

    def test_stage_events_fire_in_order(self):
        seen = []
        parse_reading(
            self.reading,
            _stage_complete(self.reading, self.wrap),
            self.db,
            on_stage=seen.append,
        )
        self.assertEqual(seen, ["bootstrap", "metadata", "sections", "section", "passes"])

    def test_a_failed_section_keeps_the_readings_already_written(self):
        reading = "Gauge:\n4 inches\n\nBody\nKnit 2 rows."

        def respond(content, **kwargs):
            if kwargs.get("schema_name") == "metadata":
                return {"name": "Gauge swatch"}
            if kwargs.get("schema_name") == "section":
                if content.lstrip().startswith("Body"):
                    raise ParseFailure("The model did not answer.")
                return _section_reading(content)
            return {"sections": ["Gauge:\n4 inches\n\n", "Body\nKnit 2 rows."]}

        with self.assertRaises(ParseFailure) as caught:
            parse_reading(reading, respond, self.db)
        self.assertEqual(str(caught.exception), "The model did not answer.")
        stored = load_project(self.db, 1)
        self.assertEqual("".join(section.text for section in stored.sections), reading)
        self.assertEqual(stored.sections[0].kind, "gauge")
        self.assertEqual(stored.sections[0].heading, "Gauge")
        self.assertIsNone(stored.sections[1].kind)

    def test_a_glossary_section_keeps_its_terms(self):
        reading = "Glossary\nRC = row count"
        stored = parse_reading(reading, _stage_complete(reading, self.wrap), self.db)
        section = stored.sections[0]
        self.assertEqual(section.kind, "glossary")
        self.assertEqual([(item.abbr, item.expansion) for item in section.glossary], [("RC", "row count")])
        self.assertEqual(load_project(self.db, stored.id), stored)

    def test_a_piece_section_keeps_how_many_to_make(self):
        reading = "Sleeve (make 2)\nKnit 2 rows."
        stored = parse_reading(reading, _stage_complete(reading, self.wrap), self.db)
        section = stored.sections[0]
        self.assertEqual(section.kind, "piece")
        self.assertEqual(section.copies, 2)
        self.assertTrue(section.procedure)
        self.assertEqual(load_project(self.db, stored.id), stored)
        self.assertEqual(stored.pieces[0].name, "Sleeve (make 2)")
        self.assertEqual(stored.pieces[0].copies, 2)
        self.assertEqual(stored.pieces[0].sizes[0].name, "Sleeve (make 2)")
        quote = stored.pieces[0].sizes[0].passes[0]
        self.assertEqual(stored.reading[quote.cite_start : quote.cite_end], "Knit 2 rows.")

    def test_passes_follow_the_size_names(self):
        reading = "Size:\nXS-M, L-2X, 3X-5X\n\nGlossary\nRC = row count\n\nBody\nKnit 2 rows."
        parts = [
            "Size:\nXS-M, L-2X, 3X-5X\n\n",
            "Glossary\nRC = row count\n\n",
            "Body\nKnit 2 rows.",
        ]

        def respond(content, **kwargs):
            if kwargs.get("schema_name") == "metadata":
                return {"name": "Wrap"}
            if kwargs.get("schema_name") == "sections":
                return {"sections": parts}
            if kwargs.get("schema_name") == "section":
                return _section_reading(content)
            if kwargs.get("schema_name") == "section_passes":
                self.assertIn("Size count: 3", content)
                self.assertIn("RC = row count", content)
                return {
                    "sizes": [
                        {"name": name, "passes": [_pass("trip", "Knit 2 rows.", count=2 + index)], "repeats": []}
                        for index, name in enumerate(SIZES)
                    ]
                }
            raise AssertionError(kwargs.get("schema_name"))

        stored = parse_reading(reading, respond, self.db)
        self.assertEqual("".join(section.text for section in stored.sections), reading)
        self.assertEqual([piece.name for piece in stored.pieces], ["Body"])
        self.assertEqual([size.name for size in stored.pieces[0].sizes], list(SIZES))
        self.assertEqual([size.passes[0].count for size in stored.pieces[0].sizes], [2, 3, 4])
        step = stored.pieces[0].sizes[0].passes[0]
        self.assertEqual(stored.reading[step.cite_start : step.cite_end], "Knit 2 rows.")
        self.assertEqual(load_project(self.db, stored.id), stored)

    def test_a_method_is_stored_with_its_passes(self):
        reading = "Knit 1 row to the left."

        def respond(content, **kwargs):
            if kwargs.get("schema_name") == "metadata":
                return {"name": "Fairisle"}
            if kwargs.get("schema_name") == "sections":
                return {"sections": [reading]}
            if kwargs.get("schema_name") == "section":
                return {
                    "kind": "method",
                    "heading": None,
                    "copies": None,
                    "procedure": True,
                    "size_names": [],
                    "glossary": [],
                }
            if kwargs.get("schema_name") == "section_passes":
                self.assertIn("Return 1 size.", content)
                return {"sizes": [{"name": "one", "passes": [_pass("trip", reading, carriage_end="left")], "repeats": []}]}
            raise AssertionError(kwargs.get("schema_name"))

        stored = parse_reading(reading, respond, self.db)
        self.assertEqual(stored.pieces[0].name, "Method")
        self.assertEqual(stored.pieces[0].copies, 1)
        self.assertEqual(stored.pieces[0].sizes[0].name, "one")
        self.assertEqual(stored.pieces[0].sizes[0].passes[0].carriage_end, "left")

    def test_chart_passes_append_after_the_steps(self):
        reading = "Read the chart from the bottom.\n\nKnit 1 row to the left."
        stages = []

        def respond(content, **kwargs):
            name = kwargs.get("schema_name")
            if name == "metadata":
                return {"name": "Fairisle"}
            if name == "sections":
                return {"sections": [reading]}
            if name == "section":
                return _method(True)
            if name == "section_passes":
                return {
                    "sizes": [
                        {"name": "one", "passes": [_pass("trip", "Knit 1 row to the left.", carriage_end="left")], "repeats": []}
                    ]
                }
            if name == "chart_passes":
                self.assertIn("row 0: 0 1", content)
                self.assertIn("Read the chart from the bottom.", content)
                return {
                    "passes": [
                        _pass(
                            "trip",
                            "Knit 1 row to the left.",
                            carriage_end="left",
                            open_point="chart_edge",
                            selections=[{"role": "holding", "method": "stitch_count", "count": 1}],
                            yarns=[{"place": "main", "name": "A"}],
                        )
                    ],
                    "repeats": [],
                }
            raise AssertionError(name)

        stored = parse_reading(
            reading,
            respond,
            self.db,
            charts=[{"grid": [[0, 1]], "colors": {"0": "#000000", "1": "#FFFFFF"}, "labels": ""}],
            on_stage=stages.append,
        )
        self.assertEqual(stages, ["bootstrap", "metadata", "sections", "section", "passes", "charts"])
        passes = stored.pieces[0].sizes[0].passes
        self.assertEqual(len(passes), 2)
        added = passes[1]
        self.assertEqual(added.open_point, "chart_edge")
        self.assertEqual(added.selections[0].count, 1)
        self.assertEqual(added.yarns[0].name, "A")
        self.assertEqual(stored.reading[added.cite_start : added.cite_end], "Knit 1 row to the left.")
        self.assertEqual(load_project(self.db, stored.id), stored)

    def test_a_chart_the_sections_do_not_explain_adds_nothing(self):
        reading = "Knit 1 row to the left."

        def respond(content, **kwargs):
            name = kwargs.get("schema_name")
            if name == "metadata":
                return {"name": "Rows"}
            if name == "sections":
                return {"sections": [reading]}
            if name == "section":
                return _method(True)
            if name == "section_passes":
                return {"sizes": [{"name": "one", "passes": [_pass("trip", reading, carriage_end="left")], "repeats": []}]}
            if name == "chart_passes":
                raise AssertionError(name)
            raise AssertionError(name)

        stored = parse_reading(
            reading,
            respond,
            self.db,
            charts=[{"grid": [[0]], "colors": {"0": "#000000"}, "labels": ""}],
        )
        self.assertEqual(len(stored.pieces[0].sizes[0].passes), 1)

    def test_a_bad_chart_cite_keeps_the_steps(self):
        reading = "Read the chart from the bottom.\n\nKnit 1 row to the left."

        def respond(content, **kwargs):
            name = kwargs.get("schema_name")
            if name == "metadata":
                return {"name": "Fairisle"}
            if name == "sections":
                return {"sections": [reading]}
            if name == "section":
                return _method(True)
            if name == "section_passes":
                return {"sizes": [{"name": "one", "passes": [_pass("trip", "Knit 1 row to the left.")], "repeats": []}]}
            if name == "chart_passes":
                return {"passes": [_pass("trip", "missing from the reading")], "repeats": []}
            raise AssertionError(name)

        with self.assertRaises(ParseFailure) as caught:
            parse_reading(
                reading,
                respond,
                self.db,
                charts=[{"grid": [[0]], "colors": {"0": "#000000"}, "labels": ""}],
            )
        self.assertEqual(str(caught.exception), "The reading did not parse.")
        stored = load_project(self.db, 1)
        self.assertEqual(len(stored.pieces[0].sizes[0].passes), 1)

    def test_two_chart_methods_are_not_guessed(self):
        parts = [
            "Manual chart.\nKnit 1 row to the left.\n\n",
            "Studio chart.\nKnit 1 row to the left.",
        ]
        reading = "".join(parts)

        def respond(content, **kwargs):
            name = kwargs.get("schema_name")
            if name == "metadata":
                return {"name": "Fairisle"}
            if name == "sections":
                return {"sections": parts}
            if name == "section":
                return _method(True)
            if name == "section_passes":
                return {"sizes": [{"name": "one", "passes": [_pass("trip", "Knit 1 row to the left.")], "repeats": []}]}
            if name == "chart_passes":
                raise AssertionError(name)
            raise AssertionError(name)

        stored = parse_reading(
            reading,
            respond,
            self.db,
            charts=[{"grid": [[0, 1]], "colors": {"0": "#000000", "1": "#FFFFFF"}, "labels": ""}],
        )
        self.assertEqual(len(stored.pieces), 2)
        self.assertTrue(all(len(piece.sizes[0].passes) == 1 for piece in stored.pieces))

    def test_a_failed_pass_keeps_the_section_readings(self):
        reading = "Body\nKnit 2 rows."

        def respond(content, **kwargs):
            if kwargs.get("schema_name") == "metadata":
                return {"name": "Body"}
            if kwargs.get("schema_name") == "sections":
                return {"sections": [reading]}
            if kwargs.get("schema_name") == "section":
                return _section_reading(content)
            raise ParseFailure("The model did not answer.")

        with self.assertRaises(ParseFailure) as caught:
            parse_reading(reading, respond, self.db)
        self.assertEqual(str(caught.exception), "The model did not answer.")
        stored = load_project(self.db, 1)
        self.assertEqual(stored.sections[0].kind, "piece")
        self.assertEqual(stored.pieces, ())


class CompleteTests(unittest.TestCase):
    def test_key_comes_from_the_env_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('# key\nexport XAI_API_KEY="from-file"\n', encoding="utf-8")
            self.assertEqual(read_key(path), "from-file")
            with self.assertRaises(ParseFailure) as caught:
                read_key(Path(tmp) / "missing.env")
            self.assertEqual(str(caught.exception), "The model key is not set.")

    def test_complete_sends_schema_and_effort(self):
        seen = {}

        def post(payload, key):
            seen["payload"] = payload
            seen["key"] = key
            return {"choices": [{"message": {"content": "{\"name\": \"Wrap\"}"}}]}

        parsed = complete(
            "Knit 2 rows.",
            schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False},
            system="Name it.",
            reasoning_effort="low",
            schema_name="metadata",
            key="secret",
            post=post,
        )
        self.assertEqual(parsed, {"name": "Wrap"})
        self.assertEqual(seen["key"], "secret")
        self.assertEqual(seen["payload"]["messages"][1]["content"], "Knit 2 rows.")
        self.assertEqual(seen["payload"]["model"], "grok-4.7")
        self.assertEqual(seen["payload"]["reasoning_effort"], "low")
        self.assertEqual(seen["payload"]["response_format"]["json_schema"]["name"], "metadata")
        encoded = json.dumps(schema())
        self.assertNotIn("machine", encoded)
        self.assertIn("passes", pass_schema()["properties"])


class AcceptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cardigan.sqlite"
        self.reading = None
        self.wrap = None
        self.fail_at = None
        self.server = make_server(0, db_path=self.path, complete=self.respond)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def respond(self, content, *, schema, system, reasoning_effort="medium", schema_name="result", on_delta=None, **_extra):
        if self.fail_at == "all":
            raise ParseFailure("The model key is not set.")
        if self.wrap is None:
            raise ParseFailure("The model did not answer.")
        return _stage_complete(self.reading or "", self.wrap, fail_at=self.fail_at)(
            content,
            schema=schema,
            system=system,
            reasoning_effort=reasoning_effort,
            schema_name=schema_name,
            on_delta=on_delta,
        )

    def test_page_names_the_parse_and_the_piece_list(self):
        page = urlopen(f"http://127.0.0.1:{self.port}/").read().decode()
        script = urlopen(f"http://127.0.0.1:{self.port}/app.js").read().decode()
        self.assertIn('id="pieces"', page)
        self.assertIn('id="settled"', page)
        self.assertIn('role="status"', page)
        self.assertIn("Parsing the reading…", script)
        self.assertIn("The reading is parsed.", script)
        self.assertIn("Try again", script)
        self.assertIn("The model did not answer.", script)
        self.assertIn("Unparsed", script)
        self.assertIn("readAccept", script)
        self.assertIn("STAGE_LABELS", script)
        self.assertIn("frozenCharts", script)
        self.assertIn("Splitting the pattern…", script)
        self.assertIn("Reading each section…", script)
        self.assertIn("Building passes…", script)

    def test_accept_on_the_wrap_sweater(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)
        body = self._post(reading)
        self.assertTrue(body["ok"], body)
        self.assertEqual("".join(body["sections"]), reading)
        self.assertGreaterEqual(len(body["sections"]), 2)
        self.assertEqual(len(body["readings"]), len(body["sections"]))
        self.assertEqual(body["readings"][1]["kind"], "piece")
        self.assertEqual(body["readings"][1]["heading"], "Body")
        self.assertEqual(body["pieces"][0]["name"], "Body")
        self.assertEqual(body["pieces"][0]["parsed"], True)
        db = connect(self.path)
        try:
            stored = load_project(db, 1)
        finally:
            db.close()
        self.assertEqual(stored.reading, reading)
        self.assertEqual(tuple(section.text for section in stored.sections), tuple(body["sections"]))

    def test_failed_accept_leaves_partial_project(self):
        reading = "Knit 2 rows."
        self.reading = reading
        self.wrap = {
            "pieces": [
                {
                    "name": "Body",
                    "copies": 1,
                    "parsed": True,
                    "sizes": [{"name": "XS-M", "passes": [_pass("trip", "Knit 2 rows.", count=2)], "repeats": []}],
                }
            ]
        }
        self.fail_at = "sections"
        body = self._post(reading)
        self.assertFalse(body["ok"])
        self.assertEqual(body["message"], "The model did not answer.")
        db = connect(self.path)
        try:
            count = db.execute("SELECT count(*) FROM project").fetchone()[0]
            stored = load_project(db, 1) if count else None
        finally:
            db.close()
        self.assertEqual(count, 1)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.name, "Wrap Sweater Scarf")

    def test_partial_accept_lists_the_unparsed_piece(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)

        def respond(content, **kwargs):
            if kwargs.get("schema_name") == "sections":
                return {"sections": ["missing sentence"]}
            return _stage_complete(reading, self.wrap)(content, **kwargs)

        self.server.complete = respond
        body = self._post(reading)
        self.assertFalse(body["ok"])
        self.assertEqual(body["message"], "The reading did not parse.")

    def test_accept_sse_includes_stage_events(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)
        events = self._events(reading)
        types = [event["type"] for event in events]
        self.assertIn("stage", types)
        self.assertEqual(events[-1]["type"], "done")
        names = [event["name"] for event in events if event["type"] == "stage"]
        self.assertEqual(names, ["bootstrap", "metadata", "sections", "section", "passes"])
        ready = [event for event in events if event["type"] == "section_ready"]
        self.assertGreaterEqual(len(ready), 2)
        self.assertEqual(ready[1]["kind"], "piece")
        self.assertEqual(ready[1]["heading"], "Body")
        pieces = [event for event in events if event["type"] == "piece_ready"]
        self.assertEqual(pieces[0]["piece"], "Body")
        self.assertGreaterEqual(pieces[0]["pass_count"], 1)

    def _post(self, reading: str, charts=None) -> dict:
        events = self._events(reading, charts=charts)
        final = events[-1]
        self.assertIn(final["type"], {"done", "error"}, final)
        return final

    def _events(self, reading: str, charts=None) -> list[dict]:
        body = {"reading": reading}
        if charts is not None:
            body["charts"] = charts
        request = Request(
            f"http://127.0.0.1:{self.port}/accept",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = urlopen(request).read().decode()
        events = []
        for block in raw.split("\n\n"):
            line = next((row for row in block.split("\n") if row.startswith("data:")), None)
            if line is None:
                continue
            events.append(json.loads(line[5:].strip()))
        self.assertTrue(events, raw)
        return events


def _crash(content, **_kwargs) -> dict:
    raise RuntimeError("socket")


def _public(project) -> dict:
    return {
        "pieces": [
            {"name": piece.name, "parsed": piece.parsed, "sizes": [size.name for size in piece.sizes]}
            for piece in project.pieces
        ]
    }


if __name__ == "__main__":
    unittest.main()
