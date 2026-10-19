"""Turn a model's reading of a pattern into a stored project.

The model quotes the reading. This module checks each piece on its own,
keeps the ones that parse, and marks the rest unparsed.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from project.model import (
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
)

Complete = Callable[..., dict]

_ENDS = {
    "left": re.compile(r"\bleft\b|\bcol\b", re.IGNORECASE),
    "right": re.compile(r"\bright\b|\bcor\b", re.IGNORECASE),
    "either": re.compile(r"\beither\b", re.IGNORECASE),
}


class ParseFailure(Exception):
    """The call failed. The accepted reading is still the reading."""


def parse_reading(
    reading: str,
    complete: Complete,
    db: sqlite3.Connection,
    *,
    charts: list | None = None,
    on_stage=None,
    on_piece_ready=None,
    on_delta=None,
) -> Project:
    """Run the staged parse pipeline. ``complete`` is the per-call LLM function."""
    from project.pipeline import run

    return run(
        reading,
        db,
        complete=complete,
        charts=charts,
        on_stage=on_stage,
        on_piece_ready=on_piece_ready,
        on_delta=on_delta,
    )


def build_size_passes(reading: str, payload: object) -> tuple[tuple[Pass, ...], tuple[Repeat, ...]]:
    """Build passes and repeats from a stage payload that has cite strings."""
    if type(payload) is not dict:
        raise ValueError("passes")
    raw_passes = payload.get("passes")
    if type(raw_passes) is not list or not raw_passes:
        raise ValueError("passes")
    cursor = 0
    passes = []
    for item in raw_passes:
        step, cursor = _pass(reading, item, cursor)
        passes.append(step)
    repeats = tuple(_repeat(item) for item in payload.get("repeats") or ())
    return tuple(passes), repeats


def _project(reading: str, payload: object) -> Project:
    if type(payload) is not dict:
        raise ParseFailure("The reading did not parse.")
    raw_pieces = payload.get("pieces")
    if type(raw_pieces) is not list or not raw_pieces:
        raise ParseFailure("The reading did not parse.")
    found: list[tuple[Piece, str]] = []
    any_parsed = False
    any_explicit = False
    for raw in raw_pieces:
        piece, kind = _one_piece(reading, raw)
        if piece is None:
            continue
        if kind == "parsed":
            any_parsed = True
        elif kind == "explicit":
            any_explicit = True
        found.append((piece, kind))
    if not any_parsed and not any_explicit:
        raise ParseFailure("The reading did not parse.")
    return Project(reading=reading, pieces=tuple(piece for piece, _kind in found))


def _one_piece(reading: str, raw: object) -> tuple[Piece | None, str]:
    if type(raw) is not dict:
        return None, "skip"
    name = _name(raw)
    if raw.get("parsed") is False:
        if name is None:
            return None, "skip"
        return _unparsed(name, raw.get("copies")), "explicit"
    try:
        return _parsed_piece(reading, raw), "parsed"
    except (TypeError, ValueError):
        if name is None:
            return None, "skip"
        return Piece(name=name, parsed=False), "invalid"


def _unparsed(name: str, copies: object) -> Piece:
    if type(copies) is not int:
        copies = 1
    try:
        return Piece(name=name, copies=copies, parsed=False)
    except ValueError:
        return Piece(name=name, parsed=False)


def _parsed_piece(reading: str, raw: dict) -> Piece:
    name = _name(raw)
    if name is None:
        raise ValueError("piece")
    copies = raw.get("copies", 1)
    raw_sizes = raw.get("sizes")
    if type(raw_sizes) is not list or not raw_sizes:
        raise ValueError("sizes")
    sizes = tuple(_size(reading, item) for item in raw_sizes)
    return Piece(name=name, copies=copies, sizes=sizes, parsed=True)


def _size(reading: str, raw: object) -> Size:
    if type(raw) is not dict:
        raise ValueError("size")
    name = raw.get("name")
    raw_passes = raw.get("passes")
    if type(raw_passes) is not list or not raw_passes:
        raise ValueError("passes")
    cursor = 0
    passes = []
    for item in raw_passes:
        step, cursor = _pass(reading, item, cursor)
        passes.append(step)
    repeats = tuple(_repeat(item) for item in raw.get("repeats") or ())
    return Size(name=name, passes=tuple(passes), repeats=repeats)


def _pass(reading: str, raw: object, cursor: int) -> tuple[Pass, int]:
    if type(raw) is not dict:
        raise ValueError("pass")
    quote = raw.get("cite")
    if type(quote) is not str or not quote:
        raise ValueError("cite")
    start = reading.find(quote, cursor)
    if start < 0:
        start = reading.find(quote)
    if start < 0:
        raise ValueError("cite is outside the reading")
    end = start + len(quote)
    carriage_end = raw.get("carriage_end")
    open_point = raw.get("open_point")
    raw_selections = raw.get("selections") or ()
    if carriage_end is not None and not _names_end(quote, carriage_end):
        carriage_end = None
        if open_point is None:
            open_point = "carriage_end"
    if open_point is None and _extra_side_unnamed(quote, raw_selections):
        open_point = "extra_needle_side"
    selections = tuple(_selection(quote, item, open_point) for item in raw_selections)
    if open_point == "extra_needle_side":
        selections = tuple(_without_side(item) for item in selections)
    counter = _counter(raw.get("row_counter"))
    step = Pass(
        kind=raw.get("kind"),
        cite_start=start,
        cite_end=end,
        count=raw.get("count", 1),
        carriage_end=carriage_end,
        row_counter=counter,
        open_point=open_point,
        selections=selections,
        settings=tuple(_setting(item) for item in raw.get("settings") or ()),
        shapes=tuple(_shape(item) for item in raw.get("shapes") or ()),
        yarns=tuple(_yarn(item) for item in raw.get("yarns") or ()),
        mark=raw.get("mark"),
    )
    return step, end


def _extra_side_unnamed(quote: str, selections: object) -> bool:
    if type(selections) is not list and type(selections) is not tuple:
        return False
    for item in selections:
        if type(item) is not dict or item.get("method") != "extra":
            continue
        side = item.get("side")
        if side is not None and not _names_end(quote, side):
            return True
    return False


def _selection(quote: str, raw: object, open_point: object) -> Selection:
    if type(raw) is not dict:
        raise ValueError("selection")
    side = raw.get("side")
    if open_point == "extra_needle_side" or (
        raw.get("method") == "extra" and side is not None and not _names_end(quote, side)
    ):
        side = None
    return Selection(
        role=raw.get("role"),
        method=raw.get("method"),
        count=raw.get("count"),
        every=raw.get("every"),
        needles_between=raw.get("needles_between"),
        between_role=raw.get("between_role"),
        needle=raw.get("needle"),
        side=side,
    )


def _without_side(item: Selection) -> Selection:
    if item.side is None:
        return item
    return Selection(
        role=item.role,
        method=item.method,
        count=item.count,
        every=item.every,
        needles_between=item.needles_between,
        between_role=item.between_role,
        needle=item.needle,
    )


def _setting(raw: object) -> CarriageSetting:
    if type(raw) is not dict:
        raise ValueError("carriage setting")
    return CarriageSetting(name=raw.get("name"), scope=raw.get("scope"))


def _shape(raw: object) -> Shape:
    if type(raw) is not dict:
        raise ValueError("shape")
    return Shape(name=raw.get("name"), count=raw.get("count"), technique=raw.get("technique"))


def _yarn(raw: object) -> Yarn:
    if type(raw) is not dict:
        raise ValueError("yarn")
    return Yarn(place=raw.get("place"), name=raw.get("name"))


def _repeat(raw: object) -> Repeat:
    if type(raw) is not dict:
        raise ValueError("repeat")
    return Repeat(first=raw.get("first"), last=raw.get("last"), times=raw.get("times"))


def _counter(raw: object) -> RowCounter | None:
    if raw is None:
        return None
    if type(raw) is not dict:
        raise ValueError("row counter")
    return RowCounter(raw.get("kind"), raw.get("value"))


def _name(raw: dict) -> str | None:
    name = raw.get("name")
    if type(name) is not str or not name.strip():
        return None
    return name.strip()


def _names_end(quote: str, end: object) -> bool:
    pattern = _ENDS.get(end) if type(end) is str else None
    if pattern is None:
        return False
    return pattern.search(quote) is not None
