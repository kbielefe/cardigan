"""Split a pattern into verbatim sections."""

from __future__ import annotations

import sqlite3

from project.complete import OnDelta, _object
from project.model import Section
from project.parse import ParseFailure
from project.stages.call import StageComplete
from project.store import save_sections

SYSTEM = """Split this machine knitting pattern into sections.

Copy the pattern unchanged. The sections stay in order, and joining them reproduces the pattern exactly, including blank lines. Keep each blank line with the section before it or the section after it.

Start a new section at a heading or a label line for a new topic. Give each of these its own section when it has its own heading or label: materials, yarn, the machine, gauge, sizes, notes, abbreviations, a glossary, a piece of the finished item, finishing, seaming, and blocking. That list is not exhaustive. A blanket, a scarf, a tutorial, and a sweater do not share the same pieces or the same surrounding sections.

A sentence that mentions yarn, the machine, or a size while explaining the project stays in the current section. The sentences under a heading stay with that heading. A heading stays in the current section only when it continues the same piece, such as a shaping step, the other side of that piece, or a chart for that piece.

Start a new section when a description of a chart or a method gives way to a numbered procedure that knits it. Instructions for seaming, finishing, or wearing the item start a new section even when they have no heading.

Page material that is not the pattern is one section for the whole run: links to other patterns, download links, subscribe lines, and an author address. An affiliate sentence inside a pattern section stays in that section.

When the opening has no headings and no label lines, keep it as one section until the first piece or the next topic break. When the pattern is one piece and one continuous set of knitting instructions, return it as one section.
"""

SCHEMA = _object(
    sections={
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "minLength": 1},
    }
)


def run_split(
    db: sqlite3.Connection,
    project_id: int,
    reading: str,
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> tuple[Section, ...]:
    payload = complete(
        reading,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="sections",
        on_delta=on_delta,
    )
    raw = payload.get("sections")
    if type(raw) is not list or not raw or any(type(item) is not str or not item for item in raw):
        raise ParseFailure("The reading did not parse.")
    return save_sections(db, project_id, tuple(Section(text=text) for text in _align(reading, raw)))


def _align(reading: str, sections: list[str]) -> list[str]:
    """Place each span back into the reading. Blank lines the model dropped stay with the previous section."""
    cursor = 0
    aligned: list[str] = []
    for section in sections:
        at = reading.find(section, cursor)
        if at < 0:
            raise ParseFailure("The reading did not parse.")
        if at > cursor:
            gap = reading[cursor:at]
            if gap.strip():
                raise ParseFailure("The reading did not parse.")
            if aligned:
                aligned[-1] += gap
            else:
                section = gap + section
        aligned.append(section)
        cursor = at + len(section)
    if cursor < len(reading):
        tail = reading[cursor:]
        if tail.strip():
            raise ParseFailure("The reading did not parse.")
        aligned[-1] += tail
    return aligned
