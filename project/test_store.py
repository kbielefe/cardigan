"""A project round-trips with no machine id."""

from __future__ import annotations

import json
import sqlite3
import unittest
from dataclasses import asdict

from project import (
    Abbreviation,
    CarriageSetting,
    Pass,
    Piece,
    Project,
    Repeat,
    RowCounter,
    Selection,
    Shape,
    Size,
    Yarn,
    connect,
    create_project,
    insert_sizes,
    load_abbreviations,
    load_project,
    replace_pieces,
    replace_size_passes,
    save_abbreviations,
    save_project,
    set_project_name,
)

READING = "\n\n".join(
    (
        "Written for the LK150.",
        "With waste yarn and ravel cord, ewrap cast on 53 sts. "
        "You will have 26 needles on one side of the bed, and the other side will have "
        "1 additional needle in work to make up the odd number. RC reset to 000.",
        "Knit 2 rows.",
        "Pull every 4th needle out to hold position, leaving 3 needles in between in working position. "
        "Make sure carriage is set not to knit the needles in hold position when moved both ways.",
        "Knit 3 rows.",
    )
)


def _span(text: str) -> tuple[int, int]:
    start = READING.index(text)
    return start, start + len(text)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")

    def tearDown(self):
        self.db.close()

    def test_wrap_body_round_trips(self):
        cast_on, knit_two, tuck, knit_three = (
            _span("With waste yarn"),
            _span("Knit 2 rows."),
            _span("Pull every 4th needle"),
            _span("Knit 3 rows."),
        )
        project = Project(
            reading=READING,
            pieces=(
                Piece(
                    name="Body",
                    sizes=(
                        Size(
                            name="XS-M",
                            passes=(
                                Pass(
                                    kind="setup",
                                    cite_start=cast_on[0],
                                    cite_end=READING.index("Knit 2 rows."),
                                    row_counter=RowCounter("reset", 0),
                                    open_point="extra_needle_side",
                                    selections=(
                                        Selection(role="working", method="each_side", count=26),
                                        Selection(role="working", method="extra", count=1),
                                    ),
                                    shapes=(Shape(name="cast_on", count=53, technique="e-wrap"),),
                                ),
                                Pass(kind="trip", count=2, cite_start=knit_two[0], cite_end=knit_two[1]),
                                Pass(
                                    kind="setup",
                                    cite_start=tuck[0],
                                    cite_end=READING.index("Knit 3 rows."),
                                    selections=(
                                        Selection(
                                            role="holding",
                                            method="every_nth",
                                            every=4,
                                            needles_between=3,
                                            between_role="working",
                                        ),
                                    ),
                                    settings=(CarriageSetting(name="hold", scope="both"),),
                                ),
                                Pass(kind="trip", count=3, cite_start=knit_three[0], cite_end=knit_three[1]),
                            ),
                        ),
                    ),
                ),
            ),
        )
        stored = save_project(self.db, project)
        self.assertEqual(load_project(self.db, stored.id), stored)
        self.assertIn("LK150", stored.reading)
        self.assertNotIn("LK150", _structured(stored))
        self.assertNotIn("TH-160", _structured(stored))
        self._schema_has_no_machine()

        passes = stored.pieces[0].sizes[0].passes
        cast = passes[0]
        self.assertEqual(cast.open_point, "extra_needle_side")
        self.assertEqual(cast.row_counter, RowCounter("reset", 0))
        self.assertIsNone(cast.selections[0].side)
        self.assertIsNone(cast.selections[1].side)
        self.assertEqual(cast.selections[0].count, 26)
        self.assertEqual(cast.selections[1].method, "extra")
        self.assertEqual(cast.shapes[0].name, "cast_on")
        self.assertEqual(cast.shapes[0].count, 53)
        self.assertEqual(cast.shapes[0].technique, "e-wrap")
        self.assertEqual(passes[1].count, 2)
        self.assertIsNone(passes[1].carriage_end)
        self.assertIsNone(passes[1].row_counter)
        self.assertEqual(passes[2].settings[0].name, "hold")
        self.assertEqual(passes[2].settings[0].scope, "both")
        self.assertEqual(passes[2].selections[0].every, 4)
        self.assertEqual(passes[2].selections[0].needles_between, 3)
        knit = passes[3]
        self.assertEqual(knit.kind, "trip")
        self.assertEqual(knit.count, 3)
        self.assertIsNone(knit.row_counter)
        self.assertIsNone(knit.carriage_end)
        self.assertIsNone(knit.open_point)
        self.assertEqual(stored.reading[knit.cite_start : knit.cite_end], "Knit 3 rows.")
        self.assertEqual(stored.pieces[0].copies, 1)

    def test_repeat_keeps_the_passes(self):
        reading = "Knit 3 rows.\n\nKnit all needles."
        project = Project(
            reading=reading,
            pieces=(
                Piece(
                    name="Body",
                    copies=2,
                    sizes=(
                        Size(
                            name="XS-M",
                            passes=(
                                Pass(kind="trip", count=3, cite_start=0, cite_end=len("Knit 3 rows.")),
                                Pass(
                                    kind="setup",
                                    cite_start=reading.index("Knit all needles."),
                                    cite_end=len(reading),
                                    settings=(CarriageSetting("knit_holding"),),
                                ),
                            ),
                            repeats=(Repeat(first=0, last=1, times=60),),
                        ),
                    ),
                ),
            ),
        )
        stored = save_project(self.db, project)
        self.assertEqual(load_project(self.db, stored.id), stored)
        size = stored.pieces[0].sizes[0]
        self.assertEqual(len(size.passes), 2)
        self.assertEqual(size.passes[0].count, 3)
        self.assertEqual(size.passes[1].settings[0].name, "knit_holding")
        self.assertEqual(size.repeats[0].times, 60)
        self.assertEqual((size.repeats[0].first, size.repeats[0].last), (0, 1))
        self.assertEqual(stored.pieces[0].copies, 2)

    def test_shared_actions_round_trip(self):
        reading = "Carriage on the left. MC in feeder. Increase 1 stitch. Mark edge stitches."
        project = Project(
            reading=reading,
            pieces=(
                Piece(
                    name="Sleeve",
                    sizes=(
                        Size(
                            name="L-2X",
                            passes=(
                                Pass(
                                    kind="trip",
                                    cite_start=0,
                                    cite_end=reading.index("Increase"),
                                    carriage_end="left",
                                    row_counter=RowCounter("checkpoint", 12),
                                    settings=(CarriageSetting("plain"),),
                                    yarns=(Yarn("main", "MC"),),
                                ),
                                Pass(
                                    kind="setup",
                                    cite_start=reading.index("Increase"),
                                    cite_end=len(reading),
                                    shapes=(Shape("increase", count=1),),
                                    mark="edge stitches",
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        stored = save_project(self.db, project)
        self.assertEqual(load_project(self.db, stored.id), stored)
        trip, setup = stored.pieces[0].sizes[0].passes
        self.assertEqual(trip.carriage_end, "left")
        self.assertEqual(trip.row_counter, RowCounter("checkpoint", 12))
        self.assertEqual(trip.yarns[0], Yarn("main", "MC", id=trip.yarns[0].id))
        self.assertEqual(setup.shapes[0].name, "increase")
        self.assertEqual(setup.mark, "edge stitches")
        self.assertEqual(Pass(kind="trip", carriage_end="either", cite_start=0, cite_end=1).carriage_end, "either")
        self.assertIsNone(Pass(kind="trip", cite_start=0, cite_end=1).carriage_end)

    def test_open_points_stay_open(self):
        with self.assertRaises(ValueError):
            Pass(
                kind="setup",
                cite_start=0,
                cite_end=1,
                open_point="extra_needle_side",
                selections=(Selection(role="working", method="extra", count=1, side="left"),),
            )
        with self.assertRaises(ValueError):
            Pass(kind="trip", cite_start=0, cite_end=1, open_point="carriage_end", carriage_end="left")
        with self.assertRaises(ValueError):
            Pass(kind="setup", count=3, cite_start=0, cite_end=1)
        with self.assertRaises(ValueError):
            Selection(role="D", method="all")
        with self.assertRaises(ValueError):
            Pass(kind="trip", carriage_end="D", cite_start=0, cite_end=1)
        with self.assertRaises(ValueError):
            Project(
                reading="Knit 3 rows.",
                pieces=(Piece(name="Body", sizes=(Size(name="XS-M", passes=(Pass(kind="trip", cite_start=0, cite_end=20),)),)),),
            )
        with self.assertRaises(ValueError):
            Size(name="XS-M", passes=(Pass(kind="trip", cite_start=0, cite_end=1),) * 2, repeats=(Repeat(0, 1, 2), Repeat(1, 1, 2)))
        with self.assertRaises(ValueError):
            Repeat(first=0, last=0, times=1)

    def test_save_of_a_stored_project_is_refused(self):
        stored = save_project(self.db, Project(reading="Knit 3 rows."))
        with self.assertRaises(ValueError):
            save_project(self.db, stored)
        with self.assertRaises(LookupError):
            load_project(self.db, stored.id + 1)

    def test_parsed_piece_may_have_empty_passes(self):
        piece = Piece(name="Body", parsed=True, sizes=(Size(name="XS-M"),))
        self.assertEqual(piece.sizes[0].passes, ())
        project = Project(reading="Knit 3 rows.", name="Wrap", pieces=(piece,))
        self.assertEqual(project.name, "Wrap")

    def test_incremental_store(self):
        project = create_project(self.db, "Knit 3 rows.\n\nBody\n\nKnit 2 rows.")
        self.assertIsNotNone(project.id)
        set_project_name(self.db, project.id, "Wrap Scarf")
        pieces = replace_pieces(
            self.db,
            project.id,
            (
                Piece(name="Body", parsed=True, sizes=()),
                Piece(name="How to Wrap", parsed=False),
            ),
        )
        self.assertEqual(len(pieces), 2)
        self.assertTrue(pieces[0].parsed)
        self.assertEqual(pieces[0].sizes, ())
        sizes = insert_sizes(self.db, pieces[0].id, (Size(name="XS-M"), Size(name="L-2X")))
        self.assertEqual([size.name for size in sizes], ["XS-M", "L-2X"])
        self.assertEqual(sizes[0].passes, ())
        trip = Pass(kind="trip", count=2, cite_start=0, cite_end=12)
        filled = replace_size_passes(self.db, sizes[0].id, (trip,))
        self.assertEqual(len(filled.passes), 1)
        save_abbreviations(self.db, project.id, (Abbreviation("RC", "row counter"),))
        self.assertEqual(load_abbreviations(self.db, project.id)[0].abbr, "RC")
        loaded = load_project(self.db, project.id)
        self.assertEqual(loaded.name, "Wrap Scarf")
        self.assertEqual(loaded.pieces[0].sizes[0].passes[0].count, 2)
        self.assertEqual(loaded.pieces[1].parsed, False)

    def test_sql_keeps_the_same_rules(self):
        stored = save_project(self.db, Project(reading="Knit 3 rows.", pieces=(Piece(name="Body", sizes=(Size(name="XS-M", passes=(Pass(kind="trip", cite_start=0, cite_end=12),)),)),)))
        size_id = stored.pieces[0].sizes[0].id
        self.assertRaises(sqlite3.IntegrityError, self._counted_setup, size_id)
        open_id = self._open_cast_on(size_id)
        self.assertRaises(sqlite3.IntegrityError, self._filled_side, open_id)
        self.assertRaises(
            sqlite3.IntegrityError,
            self.db.execute,
            "INSERT INTO needle_selection (pass_id, position, role, method) VALUES (?, 0, 'D', 'all')",
            (open_id,),
        )

    def _counted_setup(self, size_id: int):
        self.db.execute(
            """
            INSERT INTO pass (size_id, position, kind, count, cite_start, cite_end)
            VALUES (?, 1, 'setup', 3, 0, 4)
            """,
            (size_id,),
        )

    def _open_cast_on(self, size_id: int) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO pass (size_id, position, kind, count, cite_start, cite_end, open_point)
            VALUES (?, 1, 'setup', 1, 0, 4, 'extra_needle_side')
            """,
            (size_id,),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _filled_side(self, pass_id: int):
        self.db.execute(
            """
            INSERT INTO needle_selection (pass_id, position, role, method, count, side)
            VALUES (?, 0, 'working', 'extra', 1, 'left')
            """,
            (pass_id,),
        )

    def _schema_has_no_machine(self):
        tables = self.db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
        self.assertGreaterEqual(len(tables), 8)
        for table in tables:
            self.assertNotIn("machine", table["name"].lower())
            self.assertNotIn("machine", table["sql"].lower())
            columns = self.db.execute(f'PRAGMA table_info("{table["name"]}")')
            for column in columns:
                self.assertNotIn("machine", column["name"].lower())


def _structured(project: Project) -> str:
    body = asdict(project)
    body.pop("reading")
    return json.dumps(body)


if __name__ == "__main__":
    unittest.main()
