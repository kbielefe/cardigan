"""Turn one color chart into carriage passes on the method that reads it."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from project.complete import OnDelta, pass_schema
from project.model import Pass, Piece, Repeat, Section, Size
from project.parse import ParseFailure, build_size_passes
from project.stages.call import OnPieceReady, StageComplete
from project.store import replace_size_passes

SYSTEM = """Turn this color chart into carriage passes for the method that reads it.

The grid is the squares of one chart. Row 0 is the top of the picture. Column 0 is the left of the picture. colors maps each index to a hex color. The grid is not a cite.

The chart description says how to read the chart. The numbered steps are the trips that select from it. Use those words. When the description and the steps do not say whether the chart is read from the bottom or the top, return no passes and no repeats. When they do not say whether one line is one trip or one knitted row, return no passes and no repeats.

A method that says the chart is read from the bottom uses the last grid row as the first knitted row, then the row above it, up to row 0. Every grid row becomes passes. Do not stop after the first example in the numbered steps.

One chart row becomes the passes that method says that row takes. When the method knits one color on a pass, each color in the row is its own trip. Two colors are two trips. Three colors are three trips. Do not collapse two colors of one knitted row into one trip. Consecutive identical rows are one pass with a count only when the method says those rows are the same trip. Otherwise every row is its own trips and each trip has count 1.

When the method says colored or marked squares are the needles to pull, and it does not name the color, order the colors in that row from darkest to lightest. Darkness is red + green + blue, and a tie goes to the smaller red, then green, then blue. The darkest color is the first pass. The lightest color in the grid is the ground, and it is the last pass of a row that contains it. A row of one color is one pass.

On a pass, walk that row from column 0 to the last column. Each streak of that pass's color is one selection. A streak broken by another color is a new selection. The role is holding. The method is stitch_count and the count is the number of squares in the streak. A single square is a stitch count of 1. It is a needle number only when the section says where square 1 sits on the bed. Do not use needle_number when it does not.

A row 0 2 2 2 2 2, with 0 darker than 2, is two passes. The first pass has one selection, stitch count 1. The second pass has one selection, stitch count 5. Use the counts from the row you are reading.

When the section does not say which edge of the row is read first, picture order is not the needle order. Every pass that selects squares uses open_point chart_edge. A row number on the left, or the word left naming where the numbers sit, does not name that edge. Do not number the bed from the left because the picture starts there.

Set the carriage first, as its own setup, when the steps set it. The setup has no selections. Side levers on the dot are slip. Russel levers at II, or Russell levers at II, knit the holding needles. Scope is both when the words say both levers. The pass does not store Russel, Russell, or the letter D. A sentence that only sets the carriage is a setup, and its count is 1. Carriage on the right is a setup with carriage end right.

Yarn in the carriage is place main. The first pass of a knitted row is yarn A when the steps start with yarn A, and the next pass of that row is yarn B when the steps change to yarn B. Every chart row uses those letters, A then B, including rows after the first. A third color, with no letter in the steps, has a null name. The grid's color index is not a yarn name. Do not substitute a yarn named only by a label.

Carriage end is left, right, or either only on the pass whose own cite names that direction. The sentence that knits row 1 to the left names the first knitted row's first pass. A later step that says to the left names only the pass that cites that step. A pass whose cite does not name an end has a null carriage end.

Cite an exact span of the chart description or the numbered steps, copied unchanged. The same sentence may be cited by more than one pass. A label is not a cite unless those exact words are in the description or the steps. The grid is not a cite.

A repeat is stored only when the section states its times. A repeat drawn on the chart, with no count in the words, is not stored. Two widthwise repeats drawn on the chart are not a times count. Return an empty repeats array when the words give no times.

Use the shared actions. Do not name a machine, a needle letter, or a lever.
"""

SCHEMA = pass_schema()


def request_text(*, labels: str, description: str, steps: str, grid: list, colors: dict) -> str:
    """The chart, the rule for reading it, and the steps that select from it."""
    lines = [
        "Labels:",
        _block(labels),
        "",
        "Chart description:",
        _block(description),
        "",
        "Numbered steps:",
        _block(steps),
        "",
        _grid_block(grid, colors),
    ]
    return "\n".join(lines)


def build_chart_passes(text: str, payload: object) -> tuple[tuple[Pass, ...], tuple[Repeat, ...]]:
    """Passes for one chart. An empty list is a chart the sections do not say how to read."""
    if type(payload) is not dict:
        raise ParseFailure("The reading did not parse.")
    raw = payload.get("passes")
    repeats = payload.get("repeats")
    if type(raw) is not list or (repeats is not None and type(repeats) is not list):
        raise ParseFailure("The reading did not parse.")
    if not raw:
        if repeats:
            raise ParseFailure("The reading did not parse.")
        return (), ()
    try:
        return build_size_passes(text, payload)
    except (TypeError, ValueError) as exc:
        raise ParseFailure("The reading did not parse.") from exc


def run_chart_passes(
    db: sqlite3.Connection,
    reading: str,
    sections: tuple[Section, ...],
    pieces: tuple[Piece, ...],
    charts: list,
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
    on_piece_ready: OnPieceReady | None = None,
) -> None:
    """Append each chart's passes onto the method the numbered steps already stored."""
    if not charts:
        return
    found = _destination(sections, pieces)
    if found is None:
        return
    section, piece = found
    if not _mentions_chart(section.text, _description(sections)):
        return
    description = _description(sections)
    sizes = {size.id: size for size in piece.sizes if size.id is not None}
    if not sizes:
        return
    for chart in charts:
        if type(chart) is not dict:
            raise ParseFailure("The reading did not parse.")
        grid = chart.get("grid")
        colors = chart.get("colors") if type(chart.get("colors")) is dict else {}
        labels = chart.get("labels") if type(chart.get("labels")) is str else ""
        payload = complete(
            request_text(labels=labels, description=description, steps=section.text, grid=grid, colors=colors),
            schema=SCHEMA,
            system=SYSTEM,
            reasoning_effort="low",
            schema_name="chart_passes",
            on_delta=on_delta,
        )
        passes, repeats = build_chart_passes(reading, payload)
        if not passes:
            continue
        for size_id in list(sizes):
            sizes[size_id] = _append(db, piece.name, sizes[size_id], passes, repeats, on_piece_ready)


def _destination(
    sections: tuple[Section, ...],
    pieces: tuple[Piece, ...],
) -> tuple[Section, Piece] | None:
    knitting = [section for section in sections if section.kind in {"piece", "method"} and section.procedure is True]
    if len(knitting) != len(pieces):
        raise ParseFailure("The reading did not parse.")
    pairs = list(zip(knitting, pieces, strict=True))
    methods = [pair for pair in pairs if pair[0].kind == "method"]
    if len(methods) == 1:
        return methods[0]
    charted = [pair for pair in pairs if "chart" in pair[0].text.casefold()]
    if len(charted) == 1:
        return charted[0]
    if len(pairs) == 1:
        return pairs[0]
    return None


def _description(sections: tuple[Section, ...]) -> str:
    parts = [
        section.text
        for section in sections
        if section.kind == "method" and section.procedure is False and section.text.strip()
    ]
    return "\n\n".join(parts)


def _mentions_chart(steps: str, description: str) -> bool:
    folded = f"{description}\n{steps}".casefold()
    return "chart" in folded or "marked square" in folded


def _append(
    db: sqlite3.Connection,
    piece_name: str,
    size: Size,
    passes: tuple[Pass, ...],
    repeats: tuple[Repeat, ...],
    on_piece_ready: OnPieceReady | None,
) -> Size:
    if size.id is None:
        raise ParseFailure("The reading did not parse.")
    offset = len(size.passes)
    shifted = tuple(
        Repeat(first=item.first + offset, last=item.last + offset, times=item.times) for item in repeats
    )
    try:
        stored = replace_size_passes(
            db,
            size.id,
            tuple(_fresh_pass(step) for step in (*size.passes, *passes)),
            tuple(_fresh_repeat(item) for item in (*size.repeats, *shifted)),
        )
    except (TypeError, ValueError, sqlite3.IntegrityError) as exc:
        raise ParseFailure("The reading did not parse.") from exc
    if on_piece_ready is not None:
        on_piece_ready({"piece": piece_name, "size": stored.name, "pass_count": len(stored.passes)})
    return stored


def _fresh_pass(step: Pass) -> Pass:
    return replace(
        step,
        id=None,
        selections=tuple(replace(item, id=None) for item in step.selections),
        settings=tuple(replace(item, id=None) for item in step.settings),
        shapes=tuple(replace(item, id=None) for item in step.shapes),
        yarns=tuple(replace(item, id=None) for item in step.yarns),
    )


def _fresh_repeat(item: Repeat) -> Repeat:
    return replace(item, id=None)


def _block(text: str) -> str:
    if type(text) is not str or not text.strip():
        return "none"
    return text.strip()


def _grid_block(grid: list, colors: dict) -> str:
    if type(grid) is not list or not grid or any(type(row) is not list or not row for row in grid):
        raise ParseFailure("The reading did not parse.")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ParseFailure("The reading did not parse.")
    lines = ["Grid rows from the top of the picture:"]
    for index, row in enumerate(grid):
        lines.append(f"row {index}: " + " ".join(str(_cell(value)) for value in row))
    lines.append("Colors:")
    if type(colors) is not dict:
        raise ParseFailure("The reading did not parse.")
    for key in sorted(colors, key=_color_key):
        lines.append(f"{_color_key(key)} {colors[key]}")
    return "\n".join(lines)


def _color_key(key: object) -> int:
    if type(key) is str and key.lstrip("-").isdigit():
        return int(key)
    return _cell(key)


def _cell(value: object) -> int:
    if type(value) is not int:
        raise ParseFailure("The reading did not parse.")
    return value
