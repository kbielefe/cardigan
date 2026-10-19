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
from project.model import Section
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
        self.assertEqual(stored.pieces, ())

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
            return {"sections": ["Gauge:\n4 inches", "Body\nKnit 2 rows."]}

        stored = parse_reading(reading, respond, self.db)
        self.assertEqual("".join(section.text for section in stored.sections), reading)
        self.assertEqual(stored.sections[0].text, "Gauge:\n4 inches\n\n")
        self.assertEqual(stored.sections[1].text, "Body\nKnit 2 rows.")

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
        self.assertEqual(
            stored.sections,
            (Section(text="How to Wrap:\nFold it.", id=stored.sections[0].id),),
        )

    def test_stage_events_fire_in_order(self):
        seen = []
        parse_reading(
            self.reading,
            _stage_complete(self.reading, self.wrap),
            self.db,
            on_stage=seen.append,
        )
        self.assertEqual(seen, ["bootstrap", "metadata", "sections"])


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

    def test_accept_on_the_wrap_sweater(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)
        body = self._post(reading)
        self.assertTrue(body["ok"], body)
        self.assertEqual("".join(body["sections"]), reading)
        self.assertGreaterEqual(len(body["sections"]), 2)
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
        self.assertEqual(names, ["bootstrap", "metadata", "sections"])

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
