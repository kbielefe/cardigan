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
from project.model import Piece
from project.parse import ParseFailure, parse_reading
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

    def test_wrap_sweater_keeps_body_and_sleeve(self):
        for name in SIZES:
            self.assertIn(name, self.reading)
        stored = parse_reading(self.reading, _stage_complete(self.reading, self.wrap), self.db)
        self.assertEqual(load_project(self.db, stored.id), stored)
        self.assertEqual(stored.name, "Wrap Sweater Scarf")
        body, sleeve, wrap = stored.pieces
        self.assertEqual(body.name, "Body")
        self.assertEqual(sleeve.name, "Sleeve")
        self.assertEqual(sleeve.copies, 2)
        self.assertEqual(wrap.name, "How to Wrap")
        self.assertFalse(wrap.parsed)
        self.assertEqual(wrap.sizes, ())
        for piece in (body, sleeve):
            self.assertTrue(piece.parsed)
            self.assertEqual(tuple(size.name for size in piece.sizes), SIZES)
            for size in piece.sizes:
                self.assertGreaterEqual(len(size.passes), 1)
                for step in size.passes:
                    quoted = stored.reading[step.cite_start : step.cite_end]
                    self.assertTrue(quoted)
                    self.assertEqual(quoted, self.reading[step.cite_start : step.cite_end])
        cast = body.sizes[0].passes[0]
        self.assertEqual(cast.open_point, "extra_needle_side")
        self.assertTrue(all(item.side is None for item in cast.selections))
        self.assertNotIn("machine", json.dumps(_public(stored)))

    def test_failed_call_after_bootstrap_leaves_the_project(self):
        with self.assertRaises(ParseFailure) as caught:
            parse_reading(
                self.reading,
                _stage_complete(self.reading, self.wrap, fail_at="vocabulary"),
                self.db,
            )
        self.assertEqual(str(caught.exception), "The model did not answer.")
        self.assertEqual(self.db.execute("SELECT count(*) FROM project").fetchone()[0], 1)
        stored = load_project(self.db, 1)
        self.assertEqual(stored.name, "Wrap Sweater Scarf")
        self.assertGreaterEqual(len(stored.pieces), 1)

    def test_failed_call_before_answer_still_raises(self):
        with self.assertRaises(ParseFailure) as caught:
            parse_reading(self.reading, _crash, self.db)
        self.assertEqual(str(caught.exception), "The model did not answer.")

    def test_a_piece_that_does_not_parse_is_unparsed(self):
        payload = _wrap_payload(self.reading)
        for size in payload["pieces"][1]["sizes"]:
            size["passes"][0]["cite"] = "this sentence is not in the reading"
        stored = parse_reading(self.reading, _stage_complete(self.reading, payload), self.db)
        self.assertEqual([piece.name for piece in stored.pieces], ["Body", "Sleeve", "How to Wrap"])
        self.assertTrue(stored.pieces[0].parsed)
        self.assertFalse(stored.pieces[1].parsed)
        self.assertEqual(stored.pieces[1].sizes, ())
        self.assertFalse(stored.pieces[2].parsed)

    def test_every_piece_failing_stores_the_project_row(self):
        payload = {
            "pieces": [{"name": "Body", "copies": 1, "parsed": True, "sizes": []}],
        }
        with self.assertRaises(ParseFailure):
            parse_reading("Knit 2 rows.", _stage_complete("Knit 2 rows.", payload, fail_at="pieces"), self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM project").fetchone()[0], 1)

    def test_an_unnamed_end_stays_open(self):
        payload = {
            "pieces": [
                {
                    "name": "Body",
                    "copies": 1,
                    "parsed": True,
                    "sizes": [
                        {
                            "name": "XS-M",
                            "passes": [_pass("trip", "Knit 2 rows.", count=2, carriage_end="left")],
                            "repeats": [],
                        }
                    ],
                }
            ]
        }
        stored = parse_reading("Knit 2 rows.", _stage_complete("Knit 2 rows.", payload), self.db)
        step = stored.pieces[0].sizes[0].passes[0]
        self.assertIsNone(step.carriage_end)
        self.assertEqual(step.open_point, "carriage_end")

    def test_an_unnamed_extra_needle_stays_open(self):
        quote = "1 additional needle in work"
        payload = {
            "pieces": [
                {
                    "name": "Body",
                    "copies": 1,
                    "parsed": True,
                    "sizes": [
                        {
                            "name": "XS-M",
                            "passes": [
                                _pass(
                                    "setup",
                                    quote,
                                    selections=[{"role": "working", "method": "extra", "count": 1, "side": "left"}],
                                )
                            ],
                            "repeats": [],
                        }
                    ],
                }
            ]
        }
        stored = parse_reading(quote + ".", _stage_complete(quote + ".", payload), self.db)
        step = stored.pieces[0].sizes[0].passes[0]
        self.assertEqual(step.open_point, "extra_needle_side")
        self.assertIsNone(step.selections[0].side)

    def test_unparsed_piece_round_trips(self):
        payload = {"pieces": [{"name": "How to Wrap", "copies": 1, "parsed": False, "sizes": []}]}
        stored = parse_reading(
            "How to Wrap:\nFold it.",
            _stage_complete("How to Wrap:\nFold it.", payload),
            self.db,
        )
        self.assertEqual(load_project(self.db, stored.id), stored)
        self.assertEqual(stored.pieces, (Piece(name="How to Wrap", parsed=False, id=stored.pieces[0].id),))

    def test_stage_events_fire_in_order(self):
        seen = []
        parse_reading(
            self.reading,
            _stage_complete(self.reading, self.wrap),
            self.db,
            on_stage=seen.append,
        )
        self.assertEqual(
            seen[:6],
            ["bootstrap", "metadata", "pieces", "vocabulary", "sizes", "sections"],
        )
        self.assertIn("passes", seen)


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
        self.assertIn("Finding pieces…", script)

    def test_accept_on_the_wrap_sweater(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)
        body = self._post(reading)
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["pieces"][0]["name"], "Body")
        self.assertEqual(body["pieces"][0]["sizes"], list(SIZES))
        self.assertTrue(body["pieces"][0]["parsed"])
        self.assertEqual(body["pieces"][1]["name"], "Sleeve")
        self.assertEqual(body["pieces"][1]["copies"], 2)
        self.assertEqual(body["pieces"][1]["sizes"], list(SIZES))
        self.assertEqual(body["pieces"][2], {"name": "How to Wrap", "copies": 1, "parsed": False, "sizes": []})
        db = connect(self.path)
        try:
            stored = load_project(db, 1)
        finally:
            db.close()
        self.assertEqual(stored.reading, reading)
        self.assertGreaterEqual(len(stored.pieces[0].sizes[0].passes), 1)

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
        self.fail_at = "sizes"
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
        payload = _wrap_payload(reading)
        for size in payload["pieces"][1]["sizes"]:
            size["passes"][0]["cite"] = "missing sentence"
        self.wrap = payload
        body = self._post(reading)
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["pieces"][0]["name"], "Body")
        self.assertTrue(body["pieces"][0]["parsed"])
        self.assertEqual(body["pieces"][1]["name"], "Sleeve")
        self.assertFalse(body["pieces"][1]["parsed"])
        self.assertEqual(body["pieces"][1]["sizes"], [])

    def test_accept_sse_includes_stage_events(self):
        reading = _reading()
        self.reading = reading
        self.wrap = _wrap_payload(reading)
        events = self._events(reading)
        types = [event["type"] for event in events]
        self.assertIn("stage", types)
        self.assertEqual(events[-1]["type"], "done")
        names = [event["name"] for event in events if event["type"] == "stage"]
        self.assertEqual(names[0], "bootstrap")
        self.assertIn("passes", names)

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
