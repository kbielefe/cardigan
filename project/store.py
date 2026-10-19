"""Store a project in SQLite. The schema has no machine."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from project.model import (
    Abbreviation,
    CarriageSetting,
    Pass,
    Piece,
    Project,
    Repeat,
    RowCounter,
    Section,
    Selection,
    Shape,
    Size,
    Yarn,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY,
    reading TEXT NOT NULL,
    name TEXT
);

CREATE TABLE IF NOT EXISTS abbreviation (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    abbr TEXT NOT NULL CHECK (length(trim(abbr)) > 0),
    expansion TEXT NOT NULL CHECK (length(trim(expansion)) > 0),
    UNIQUE (project_id, position)
);

CREATE TABLE IF NOT EXISTS section (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL CHECK (length(text) > 0),
    kind TEXT CHECK (kind IS NULL OR kind IN (
        'piece', 'method', 'glossary', 'gauge', 'sizes', 'yarn', 'machine', 'notes', 'finishing', 'page'
    )),
    heading TEXT CHECK (heading IS NULL OR length(trim(heading)) > 0),
    copies INTEGER CHECK (copies IS NULL OR copies >= 1),
    procedure INTEGER CHECK (procedure IS NULL OR procedure IN (0, 1)),
    UNIQUE (project_id, position),
    CHECK (kind IS NULL OR procedure IS NOT NULL),
    CHECK (kind = 'piece' OR copies IS NULL)
);

CREATE TABLE IF NOT EXISTS section_size (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES section (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    UNIQUE (section_id, position)
);

CREATE TABLE IF NOT EXISTS section_glossary (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES section (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    abbr TEXT NOT NULL CHECK (length(trim(abbr)) > 0),
    expansion TEXT NOT NULL CHECK (length(trim(expansion)) > 0),
    UNIQUE (section_id, position)
);

CREATE TABLE IF NOT EXISTS piece (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(name) > 0),
    copies INTEGER NOT NULL CHECK (copies >= 1),
    parsed INTEGER NOT NULL CHECK (parsed IN (0, 1)),
    UNIQUE (project_id, position)
);

CREATE TABLE IF NOT EXISTS size (
    id INTEGER PRIMARY KEY,
    piece_id INTEGER NOT NULL REFERENCES piece (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(name) > 0),
    UNIQUE (piece_id, position)
);

CREATE TABLE IF NOT EXISTS pass (
    id INTEGER PRIMARY KEY,
    size_id INTEGER NOT NULL REFERENCES size (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('setup', 'trip')),
    count INTEGER NOT NULL CHECK (count >= 1),
    carriage_end TEXT CHECK (carriage_end IN ('left', 'right', 'either')),
    row_counter_kind TEXT CHECK (row_counter_kind IN ('reset', 'checkpoint', 'target')),
    row_counter_value INTEGER CHECK (row_counter_value IS NULL OR row_counter_value >= 0),
    cite_start INTEGER NOT NULL CHECK (cite_start >= 0),
    cite_end INTEGER NOT NULL CHECK (cite_end >= cite_start),
    open_point TEXT CHECK (open_point IN (
        'shaping_moment', 'number_kind', 'extra_needle_side', 'row_or_trips',
        'carriage_end', 'needle_letter', 'unknown_counter'
    )),
    mark TEXT CHECK (mark IS NULL OR length(trim(mark)) > 0),
    UNIQUE (size_id, position),
    CHECK (kind = 'trip' OR count = 1),
    CHECK ((row_counter_kind IS NULL) = (row_counter_value IS NULL)),
    CHECK (open_point IS NULL OR open_point != 'carriage_end' OR carriage_end IS NULL)
);

CREATE TABLE IF NOT EXISTS pass_repeat (
    id INTEGER PRIMARY KEY,
    size_id INTEGER NOT NULL REFERENCES size (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    first_pass_position INTEGER NOT NULL CHECK (first_pass_position >= 0),
    last_pass_position INTEGER NOT NULL,
    times INTEGER NOT NULL CHECK (times >= 2),
    UNIQUE (size_id, position),
    CHECK (last_pass_position >= first_pass_position)
);

CREATE TABLE IF NOT EXISTS needle_selection (
    id INTEGER PRIMARY KEY,
    pass_id INTEGER NOT NULL REFERENCES pass (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('out_of_work', 'working', 'upper', 'holding')),
    method TEXT NOT NULL CHECK (method IN (
        'stitch_count', 'each_side', 'extra', 'every_nth', 'needle_number', 'side', 'edge', 'all'
    )),
    count INTEGER CHECK (count IS NULL OR count >= 1),
    every INTEGER CHECK (every IS NULL OR every >= 2),
    needles_between INTEGER CHECK (needles_between IS NULL OR needles_between >= 1),
    between_role TEXT CHECK (between_role IN ('out_of_work', 'working', 'upper', 'holding')),
    needle INTEGER,
    side TEXT CHECK (side IN ('left', 'right')),
    UNIQUE (pass_id, position),
    CHECK (
        (method = 'stitch_count' AND count IS NOT NULL AND every IS NULL
            AND needles_between IS NULL AND between_role IS NULL AND needle IS NULL AND side IS NULL)
        OR (method = 'each_side' AND count IS NOT NULL AND every IS NULL
            AND needles_between IS NULL AND between_role IS NULL AND needle IS NULL)
        OR (method = 'extra' AND count IS NOT NULL AND every IS NULL
            AND needles_between IS NULL AND between_role IS NULL AND needle IS NULL)
        OR (method = 'every_nth' AND every IS NOT NULL AND count IS NULL AND needle IS NULL AND side IS NULL
            AND (needles_between IS NULL) = (between_role IS NULL))
        OR (method = 'needle_number' AND needle IS NOT NULL AND count IS NULL AND every IS NULL
            AND needles_between IS NULL AND between_role IS NULL AND side IS NULL)
        OR (method = 'side' AND side IS NOT NULL AND count IS NULL AND every IS NULL
            AND needles_between IS NULL AND between_role IS NULL AND needle IS NULL)
        OR (method = 'edge' AND every IS NULL AND needles_between IS NULL AND between_role IS NULL
            AND needle IS NULL)
        OR (method = 'all' AND count IS NULL AND every IS NULL AND needles_between IS NULL
            AND between_role IS NULL AND needle IS NULL AND side IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS carriage_setting (
    id INTEGER PRIMARY KEY,
    pass_id INTEGER NOT NULL REFERENCES pass (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (name IN ('plain', 'slip', 'hold', 'knit_holding', 'tuck', 'intarsia')),
    scope TEXT CHECK (scope IN ('left', 'right', 'both')),
    UNIQUE (pass_id, position)
);

CREATE TABLE IF NOT EXISTS shape (
    id INTEGER PRIMARY KEY,
    pass_id INTEGER NOT NULL REFERENCES pass (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (name IN (
        'increase', 'decrease', 'transfer', 'move', 'short_row_wrap', 'bind_off', 'cast_on', 'scrap_off'
    )),
    count INTEGER CHECK (count IS NULL OR count >= 1),
    technique TEXT CHECK (technique IS NULL OR technique = 'e-wrap'),
    UNIQUE (pass_id, position),
    CHECK (technique IS NULL OR name = 'cast_on')
);

CREATE TABLE IF NOT EXISTS yarn (
    id INTEGER PRIMARY KEY,
    pass_id INTEGER NOT NULL REFERENCES pass (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    place TEXT NOT NULL CHECK (place IN ('main', 'plating', 'unnamed', 'rest')),
    name TEXT CHECK (name IS NULL OR length(trim(name)) > 0),
    UNIQUE (pass_id, position)
);

CREATE TRIGGER IF NOT EXISTS pass_cite_in_reading
BEFORE INSERT ON pass
FOR EACH ROW
WHEN NEW.cite_end > (
    SELECT length(project.reading)
    FROM size
    JOIN piece ON piece.id = size.piece_id
    JOIN project ON project.id = piece.project_id
    WHERE size.id = NEW.size_id
)
BEGIN
    SELECT RAISE(ABORT, 'citation is outside the reading');
END;

CREATE TRIGGER IF NOT EXISTS selection_open_side
BEFORE INSERT ON needle_selection
FOR EACH ROW
WHEN NEW.side IS NOT NULL
    AND (SELECT open_point FROM pass WHERE id = NEW.pass_id) = 'extra_needle_side'
BEGIN
    SELECT RAISE(ABORT, 'the extra needle side is open');
END;

CREATE TRIGGER IF NOT EXISTS repeat_inside_passes
BEFORE INSERT ON pass_repeat
FOR EACH ROW
WHEN NEW.last_pass_position >= (SELECT count(*) FROM pass WHERE size_id = NEW.size_id)
BEGIN
    SELECT RAISE(ABORT, 'repeat is outside the passes');
END;

CREATE TRIGGER IF NOT EXISTS unparsed_piece_has_no_sizes
BEFORE INSERT ON size
FOR EACH ROW
WHEN (SELECT parsed FROM piece WHERE id = NEW.piece_id) = 0
BEGIN
    SELECT RAISE(ABORT, 'an unparsed piece has no sizes');
END;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    prepare(db)
    return db


def prepare(db: sqlite3.Connection) -> None:
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    _migrate(db)


def _migrate(db: sqlite3.Connection) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(project)")}
    if "name" not in columns:
        db.execute("ALTER TABLE project ADD COLUMN name TEXT")
    section_columns = {row["name"] for row in db.execute("PRAGMA table_info(section)")}
    if section_columns and "kind" not in section_columns:
        db.execute("ALTER TABLE section ADD COLUMN kind TEXT")
        db.execute("ALTER TABLE section ADD COLUMN heading TEXT")
        db.execute("ALTER TABLE section ADD COLUMN copies INTEGER")
        db.execute("ALTER TABLE section ADD COLUMN procedure INTEGER")


def create_project(db: sqlite3.Connection, reading: str) -> Project:
    prepare(db)
    if type(reading) is not str:
        raise ValueError("reading must be text")
    with db:
        project_id = _rowid(db.execute("INSERT INTO project (reading) VALUES (?)", (reading,)))
    return Project(reading=reading, id=project_id)


def set_project_name(db: sqlite3.Connection, project_id: int, name: str | None) -> None:
    prepare(db)
    if name is not None:
        name = name.strip() or None
    with db:
        cursor = db.execute("UPDATE project SET name = ? WHERE id = ?", (name, project_id))
        if cursor.rowcount != 1:
            raise LookupError(f"no project {project_id}")


def save_sections(db: sqlite3.Connection, project_id: int, sections: tuple[Section, ...]) -> tuple[Section, ...]:
    prepare(db)
    if any(item.id is not None for item in sections):
        raise ValueError("save sections inserts new rows")
    with db:
        if db.execute("SELECT id FROM project WHERE id = ?", (project_id,)).fetchone() is None:
            raise LookupError(f"no project {project_id}")
        db.execute("DELETE FROM section WHERE project_id = ?", (project_id,))
        stored = []
        for index, item in enumerate(sections):
            item_id = _rowid(
                db.execute(
                    "INSERT INTO section (project_id, position, text) VALUES (?, ?, ?)",
                    (project_id, index, item.text),
                )
            )
            stored.append(replace(item, id=item_id))
    return tuple(stored)


def load_sections(db: sqlite3.Connection, project_id: int) -> tuple[Section, ...]:
    prepare(db)
    return tuple(_load_section(db, row) for row in _at(db, "section", "project_id", project_id))


def save_section_reading(db: sqlite3.Connection, section: Section) -> Section:
    """Write this section's reading. The verbatim text stays as the split stored it."""
    prepare(db)
    if section.id is None or section.kind is None:
        raise ValueError("a section reading updates a stored section")
    with db:
        row = db.execute("SELECT id, text FROM section WHERE id = ?", (section.id,)).fetchone()
        if row is None:
            raise LookupError(f"no section {section.id}")
        if row["text"] != section.text:
            raise ValueError("a section reading does not change the section text")
        db.execute(
            """
            UPDATE section
            SET kind = ?, heading = ?, copies = ?, procedure = ?
            WHERE id = ?
            """,
            (
                section.kind,
                section.heading,
                section.copies,
                int(section.procedure) if section.procedure is not None else None,
                section.id,
            ),
        )
        db.execute("DELETE FROM section_size WHERE section_id = ?", (section.id,))
        db.execute("DELETE FROM section_glossary WHERE section_id = ?", (section.id,))
        size_names = tuple(
            _insert_section_size(db, section.id, index, name) for index, name in enumerate(section.size_names)
        )
        glossary = tuple(
            _insert_section_term(db, section.id, index, item) for index, item in enumerate(section.glossary)
        )
    return replace(section, size_names=size_names, glossary=glossary)


def replace_pieces(db: sqlite3.Connection, project_id: int, pieces: tuple[Piece, ...]) -> tuple[Piece, ...]:
    prepare(db)
    _fresh_pieces(pieces)
    with db:
        if db.execute("SELECT id FROM project WHERE id = ?", (project_id,)).fetchone() is None:
            raise LookupError(f"no project {project_id}")
        db.execute("DELETE FROM piece WHERE project_id = ?", (project_id,))
        return tuple(_insert_piece(db, project_id, index, piece) for index, piece in enumerate(pieces))


def insert_sizes(db: sqlite3.Connection, piece_id: int, sizes: tuple[Size, ...]) -> tuple[Size, ...]:
    prepare(db)
    for size in sizes:
        if size.id is not None:
            raise ValueError("insert sizes inserts new sizes")
        if size.passes or size.repeats:
            raise ValueError("insert sizes starts with empty passes")
    with db:
        row = db.execute("SELECT id, parsed FROM piece WHERE id = ?", (piece_id,)).fetchone()
        if row is None:
            raise LookupError(f"no piece {piece_id}")
        if not row["parsed"]:
            raise ValueError("an unparsed piece has no sizes")
        db.execute("DELETE FROM size WHERE piece_id = ?", (piece_id,))
        return tuple(_insert_size(db, piece_id, index, size) for index, size in enumerate(sizes))


def replace_size_passes(
    db: sqlite3.Connection,
    size_id: int,
    passes: tuple[Pass, ...],
    repeats: tuple[Repeat, ...] = (),
) -> Size:
    prepare(db)
    for step in passes:
        if step.id is not None or _child_ids(step):
            raise ValueError("replace size passes inserts new passes")
    if any(repeat.id is not None for repeat in repeats):
        raise ValueError("replace size passes inserts new repeats")
    with db:
        row = db.execute("SELECT id, name FROM size WHERE id = ?", (size_id,)).fetchone()
        if row is None:
            raise LookupError(f"no size {size_id}")
        Size(name=row["name"], passes=passes, repeats=repeats)
        db.execute("DELETE FROM pass WHERE size_id = ?", (size_id,))
        db.execute("DELETE FROM pass_repeat WHERE size_id = ?", (size_id,))
        stored_passes = tuple(_insert_pass(db, size_id, index, step) for index, step in enumerate(passes))
        stored_repeats = tuple(
            _insert_repeat(db, size_id, index, repeat) for index, repeat in enumerate(repeats)
        )
    return Size(name=row["name"], passes=stored_passes, repeats=stored_repeats, id=size_id)


def save_abbreviations(
    db: sqlite3.Connection,
    project_id: int,
    abbreviations: tuple[Abbreviation, ...],
) -> tuple[Abbreviation, ...]:
    prepare(db)
    if any(item.id is not None for item in abbreviations):
        raise ValueError("save abbreviations inserts new rows")
    with db:
        if db.execute("SELECT id FROM project WHERE id = ?", (project_id,)).fetchone() is None:
            raise LookupError(f"no project {project_id}")
        db.execute("DELETE FROM abbreviation WHERE project_id = ?", (project_id,))
        stored = []
        for index, item in enumerate(abbreviations):
            item_id = _rowid(
                db.execute(
                    "INSERT INTO abbreviation (project_id, position, abbr, expansion) VALUES (?, ?, ?, ?)",
                    (project_id, index, item.abbr, item.expansion),
                )
            )
            stored.append(replace(item, id=item_id))
    return tuple(stored)


def load_abbreviations(db: sqlite3.Connection, project_id: int) -> tuple[Abbreviation, ...]:
    prepare(db)
    return tuple(
        Abbreviation(abbr=row["abbr"], expansion=row["expansion"], id=row["id"])
        for row in _at(db, "abbreviation", "project_id", project_id)
    )


def save_project(db: sqlite3.Connection, project: Project) -> Project:
    prepare(db)
    _new(project)
    with db:
        project_id = _rowid(
            db.execute(
                "INSERT INTO project (reading, name) VALUES (?, ?)",
                (project.reading, project.name),
            )
        )
        pieces = tuple(_insert_piece(db, project_id, index, piece) for index, piece in enumerate(project.pieces))
        sections = tuple(_insert_section(db, project_id, index, item) for index, item in enumerate(project.sections))
    return replace(project, id=project_id, pieces=pieces, sections=sections)


def load_project(db: sqlite3.Connection, project_id: int) -> Project:
    prepare(db)
    row = db.execute("SELECT id, reading, name FROM project WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise LookupError(f"no project {project_id}")
    pieces = tuple(
        _load_piece(db, piece)
        for piece in _at(db, "piece", "project_id", row["id"])
    )
    sections = load_sections(db, row["id"])
    return Project(reading=row["reading"], pieces=pieces, sections=sections, name=row["name"], id=row["id"])


def _insert_section(db: sqlite3.Connection, project_id: int, position: int, item: Section) -> Section:
    item_id = _rowid(
        db.execute(
            """
            INSERT INTO section (project_id, position, text, kind, heading, copies, procedure)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                position,
                item.text,
                item.kind,
                item.heading,
                item.copies,
                None if item.procedure is None else int(item.procedure),
            ),
        )
    )
    size_names = tuple(_insert_section_size(db, item_id, index, name) for index, name in enumerate(item.size_names))
    glossary = tuple(_insert_section_term(db, item_id, index, term) for index, term in enumerate(item.glossary))
    return replace(item, id=item_id, size_names=size_names, glossary=glossary)


def _insert_section_size(db: sqlite3.Connection, section_id: int, position: int, name: str) -> str:
    db.execute(
        "INSERT INTO section_size (section_id, position, name) VALUES (?, ?, ?)",
        (section_id, position, name),
    )
    return name


def _insert_section_term(db: sqlite3.Connection, section_id: int, position: int, item: Abbreviation) -> Abbreviation:
    item_id = _rowid(
        db.execute(
            "INSERT INTO section_glossary (section_id, position, abbr, expansion) VALUES (?, ?, ?, ?)",
            (section_id, position, item.abbr, item.expansion),
        )
    )
    return replace(item, id=item_id)


def _load_section(db: sqlite3.Connection, row: sqlite3.Row) -> Section:
    if row["kind"] is None:
        return Section(text=row["text"], id=row["id"])
    return Section(
        text=row["text"],
        id=row["id"],
        kind=row["kind"],
        heading=row["heading"],
        copies=row["copies"],
        procedure=bool(row["procedure"]),
        size_names=tuple(item["name"] for item in _at(db, "section_size", "section_id", row["id"])),
        glossary=tuple(
            Abbreviation(abbr=item["abbr"], expansion=item["expansion"], id=item["id"])
            for item in _at(db, "section_glossary", "section_id", row["id"])
        ),
    )


def _new(project: Project) -> None:
    if project.id is not None:
        raise ValueError("save inserts a new project")
    if any(item.id is not None for item in project.sections):
        raise ValueError("save inserts a new project")
    _fresh_pieces(project.pieces)


def _fresh_pieces(pieces: tuple[Piece, ...]) -> None:
    for piece in pieces:
        if piece.id is not None:
            raise ValueError("save inserts a new project")
        for size in piece.sizes:
            if size.id is not None:
                raise ValueError("save inserts a new project")
            for step in size.passes:
                if step.id is not None or _child_ids(step):
                    raise ValueError("save inserts a new project")
            if any(repeat.id is not None for repeat in size.repeats):
                raise ValueError("save inserts a new project")


def _child_ids(step: Pass) -> bool:
    rows = (*step.selections, *step.settings, *step.shapes, *step.yarns)
    return any(row.id is not None for row in rows)


def _insert_piece(db: sqlite3.Connection, project_id: int, position: int, piece: Piece) -> Piece:
    piece_id = _rowid(
        db.execute(
            "INSERT INTO piece (project_id, position, name, copies, parsed) VALUES (?, ?, ?, ?, ?)",
            (project_id, position, piece.name, piece.copies, int(piece.parsed)),
        )
    )
    sizes = tuple(_insert_size(db, piece_id, index, size) for index, size in enumerate(piece.sizes))
    return replace(piece, id=piece_id, sizes=sizes)


def _insert_size(db: sqlite3.Connection, piece_id: int, position: int, size: Size) -> Size:
    size_id = _rowid(
        db.execute(
            "INSERT INTO size (piece_id, position, name) VALUES (?, ?, ?)",
            (piece_id, position, size.name),
        )
    )
    passes = tuple(_insert_pass(db, size_id, index, step) for index, step in enumerate(size.passes))
    repeats = tuple(_insert_repeat(db, size_id, index, repeat) for index, repeat in enumerate(size.repeats))
    return replace(size, id=size_id, passes=passes, repeats=repeats)


def _insert_pass(db: sqlite3.Connection, size_id: int, position: int, step: Pass) -> Pass:
    counter = step.row_counter
    pass_id = _rowid(
        db.execute(
            """
            INSERT INTO pass (
                size_id, position, kind, count, carriage_end,
                row_counter_kind, row_counter_value, cite_start, cite_end, open_point, mark
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                size_id,
                position,
                step.kind,
                step.count,
                step.carriage_end,
                None if counter is None else counter.kind,
                None if counter is None else counter.value,
                step.cite_start,
                step.cite_end,
                step.open_point,
                step.mark,
            ),
        )
    )
    selections = tuple(_insert_selection(db, pass_id, index, item) for index, item in enumerate(step.selections))
    settings = tuple(_insert_setting(db, pass_id, index, item) for index, item in enumerate(step.settings))
    shapes = tuple(_insert_shape(db, pass_id, index, item) for index, item in enumerate(step.shapes))
    yarns = tuple(_insert_yarn(db, pass_id, index, item) for index, item in enumerate(step.yarns))
    return replace(step, id=pass_id, selections=selections, settings=settings, shapes=shapes, yarns=yarns)


def _insert_selection(db: sqlite3.Connection, pass_id: int, position: int, item: Selection) -> Selection:
    item_id = _rowid(
        db.execute(
            """
            INSERT INTO needle_selection (
                pass_id, position, role, method, count, every, needles_between, between_role, needle, side
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pass_id,
                position,
                item.role,
                item.method,
                item.count,
                item.every,
                item.needles_between,
                item.between_role,
                item.needle,
                item.side,
            ),
        )
    )
    return replace(item, id=item_id)


def _insert_setting(db: sqlite3.Connection, pass_id: int, position: int, item: CarriageSetting) -> CarriageSetting:
    item_id = _rowid(
        db.execute(
            "INSERT INTO carriage_setting (pass_id, position, name, scope) VALUES (?, ?, ?, ?)",
            (pass_id, position, item.name, item.scope),
        )
    )
    return replace(item, id=item_id)


def _insert_shape(db: sqlite3.Connection, pass_id: int, position: int, item: Shape) -> Shape:
    item_id = _rowid(
        db.execute(
            "INSERT INTO shape (pass_id, position, name, count, technique) VALUES (?, ?, ?, ?, ?)",
            (pass_id, position, item.name, item.count, item.technique),
        )
    )
    return replace(item, id=item_id)


def _insert_yarn(db: sqlite3.Connection, pass_id: int, position: int, item: Yarn) -> Yarn:
    item_id = _rowid(
        db.execute(
            "INSERT INTO yarn (pass_id, position, place, name) VALUES (?, ?, ?, ?)",
            (pass_id, position, item.place, item.name),
        )
    )
    return replace(item, id=item_id)


def _insert_repeat(db: sqlite3.Connection, size_id: int, position: int, repeat: Repeat) -> Repeat:
    repeat_id = _rowid(
        db.execute(
            """
            INSERT INTO pass_repeat (size_id, position, first_pass_position, last_pass_position, times)
            VALUES (?, ?, ?, ?, ?)
            """,
            (size_id, position, repeat.first, repeat.last, repeat.times),
        )
    )
    return replace(repeat, id=repeat_id)


def _load_piece(db: sqlite3.Connection, row: sqlite3.Row) -> Piece:
    sizes = tuple(_load_size(db, size) for size in _at(db, "size", "piece_id", row["id"]))
    return Piece(
        name=row["name"],
        sizes=sizes,
        copies=row["copies"],
        parsed=bool(row["parsed"]),
        id=row["id"],
    )


def _load_size(db: sqlite3.Connection, row: sqlite3.Row) -> Size:
    passes = tuple(_load_pass(db, step) for step in _at(db, "pass", "size_id", row["id"]))
    repeats = tuple(
        Repeat(
            first=repeat["first_pass_position"],
            last=repeat["last_pass_position"],
            times=repeat["times"],
            id=repeat["id"],
        )
        for repeat in _at(db, "pass_repeat", "size_id", row["id"])
    )
    return Size(name=row["name"], passes=passes, repeats=repeats, id=row["id"])


def _load_pass(db: sqlite3.Connection, row: sqlite3.Row) -> Pass:
    if row["row_counter_kind"] is None:
        counter = None
    else:
        counter = RowCounter(row["row_counter_kind"], row["row_counter_value"])
    return Pass(
        kind=row["kind"],
        cite_start=row["cite_start"],
        cite_end=row["cite_end"],
        count=row["count"],
        carriage_end=row["carriage_end"],
        row_counter=counter,
        open_point=row["open_point"],
        selections=tuple(_load_selection(item) for item in _at(db, "needle_selection", "pass_id", row["id"])),
        settings=tuple(
            CarriageSetting(name=item["name"], scope=item["scope"], id=item["id"])
            for item in _at(db, "carriage_setting", "pass_id", row["id"])
        ),
        shapes=tuple(
            Shape(name=item["name"], count=item["count"], technique=item["technique"], id=item["id"])
            for item in _at(db, "shape", "pass_id", row["id"])
        ),
        yarns=tuple(
            Yarn(place=item["place"], name=item["name"], id=item["id"])
            for item in _at(db, "yarn", "pass_id", row["id"])
        ),
        mark=row["mark"],
        id=row["id"],
    )


def _load_selection(row: sqlite3.Row) -> Selection:
    return Selection(
        role=row["role"],
        method=row["method"],
        count=row["count"],
        every=row["every"],
        needles_between=row["needles_between"],
        between_role=row["between_role"],
        needle=row["needle"],
        side=row["side"],
        id=row["id"],
    )


def _at(db: sqlite3.Connection, table: str, column: str, parent: int) -> list[sqlite3.Row]:
    rows = list(db.execute(f"SELECT * FROM {table} WHERE {column} = ? ORDER BY position", (parent,)))
    for index, row in enumerate(rows):
        if row["position"] != index:
            raise ValueError(f"{table} positions are not contiguous")
    return rows


def _rowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("insert did not return an id")
    return cursor.lastrowid
