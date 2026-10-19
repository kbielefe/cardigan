"""Sizes stage: empty size rows per parsed piece."""

from __future__ import annotations

import sqlite3

from project import domain
from project.complete import OnDelta, _object
from project.model import Abbreviation, Piece, Size
from project.stages.call import StageComplete
from project.store import insert_sizes

SYSTEM = """List the size names for this piece of the pattern.

Use the size line from the reading. Return one name per size in reading order. Do not invent sizes that are not in the reading. If the piece has no size line, return one size named for the whole piece (often the piece name or \"one\").
"""

SCHEMA = _object(
    sizes={
        "type": "array",
        "items": _object(name={"type": "string"}),
    }
)


def run_sizes(
    db: sqlite3.Connection,
    reading: str,
    pieces: tuple[Piece, ...],
    piece_cites: dict[int, str],
    abbreviations: tuple[Abbreviation, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> dict[int, tuple[Size, ...]]:
    size_rules = domain.inject("Sizes")
    vocab = _vocab_block(abbreviations)
    system = SYSTEM if not size_rules else f"{SYSTEM}\n\n{size_rules}"
    if vocab:
        system = f"{system}\n\n{vocab}"
    by_piece: dict[int, tuple[Size, ...]] = {}
    for piece in pieces:
        if not piece.parsed or piece.id is None:
            continue
        cite = piece_cites.get(piece.id) or piece.name
        content = f"Piece: {piece.name}\n\n{cite}\n\nFull reading follows if needed:\n{reading}"
        payload = complete(
            content,
            schema=SCHEMA,
            system=system,
            reasoning_effort="low",
            schema_name="sizes",
            on_delta=on_delta,
        )
        raw = payload.get("sizes")
        sizes: list[Size] = []
        if type(raw) is list:
            for item in raw:
                if type(item) is not dict:
                    continue
                name = item.get("name")
                if type(name) is not str or not name.strip():
                    continue
                sizes.append(Size(name=name.strip(), passes=(), repeats=()))
        if not sizes:
            sizes.append(Size(name="one", passes=(), repeats=()))
        by_piece[piece.id] = insert_sizes(db, piece.id, tuple(sizes))
    return by_piece


def _vocab_block(abbreviations: tuple[Abbreviation, ...]) -> str:
    if not abbreviations:
        return ""
    lines = "\n".join(f"{item.abbr} = {item.expansion}" for item in abbreviations)
    return f"Pattern abbreviations:\n{lines}"
