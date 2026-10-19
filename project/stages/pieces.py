"""Piece outline stage."""

from __future__ import annotations

import sqlite3

from project import domain
from project.complete import OnDelta, _object
from project.model import Piece
from project.parse import ParseFailure
from project.stages.call import StageComplete
from project.store import replace_pieces

SYSTEM = """List the pieces in this frozen knitting reading.

Each piece has a name, copies, parsed, and a cite. The cite is an exact span from the reading that identifies the piece (usually its heading and opening lines).

parsed is true when the piece becomes carriage passes. Seaming, blocking, construction, how to wrap, finishing, glossary, and materials are parsed false and have no sizes later.

A parenthesis of words such as (make 2) is the copies of that piece.
"""

SCHEMA = _object(
    pieces={
        "type": "array",
        "items": _object(
            name={"type": "string"},
            copies={"type": "integer", "minimum": 1},
            parsed={"type": "boolean"},
            cite={"type": "string"},
        ),
    }
)


def run_pieces(
    db: sqlite3.Connection,
    project_id: int,
    reading: str,
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> tuple[tuple[Piece, ...], dict[int, str]]:
    sections = domain.inject("Sections of a pattern")
    system = SYSTEM if not sections else f"{SYSTEM}\n\n{sections}"
    payload = complete(
        reading,
        schema=SCHEMA,
        system=system,
        reasoning_effort="medium",
        schema_name="pieces",
        on_delta=on_delta,
    )
    raw = payload.get("pieces")
    if type(raw) is not list or not raw:
        raise ParseFailure("The reading did not parse.")
    pieces: list[Piece] = []
    cites: list[str] = []
    any_parsed = False
    any_explicit = False
    for item in raw:
        if type(item) is not dict:
            continue
        name = item.get("name")
        if type(name) is not str or not name.strip():
            continue
        name = name.strip()
        copies = item.get("copies", 1)
        if type(copies) is not int or copies < 1:
            copies = 1
        cite = item.get("cite")
        if type(cite) is not str:
            cite = ""
        if item.get("parsed") is False:
            pieces.append(Piece(name=name, copies=copies, parsed=False))
            cites.append(cite)
            any_explicit = True
            continue
        pieces.append(Piece(name=name, copies=copies, parsed=True, sizes=()))
        cites.append(cite)
        any_parsed = True
    if not any_parsed and not any_explicit:
        raise ParseFailure("The reading did not parse.")
    stored = replace_pieces(db, project_id, tuple(pieces))
    cite_by_id = {piece.id: cite for piece, cite in zip(stored, cites) if piece.id is not None}
    return stored, cite_by_id
