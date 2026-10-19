"""Read one verbatim section into the facts written in it."""

from __future__ import annotations

import sqlite3

from project.complete import OnDelta, _enum, _nullable, _object
from project.model import SECTION_KINDS, Abbreviation, Section
from project.parse import ParseFailure
from project.stages.call import StageComplete
from project.store import save_section_reading

SYSTEM = """Read this one section of a machine knitting pattern. Say what kind of section it is, and return only the facts written in it.

kind is one of: piece, method, glossary, gauge, sizes, yarn, machine, notes, finishing, page.

A piece is the knitting of one part of the finished item: Body, Sleeve, Front, Back, and the same kind of heading on a blanket or a scarf. A heading inside that part stays part of the piece. Begin Neck Shaping is still the Front. Sleeve (make 2) is one piece, and copies is 2. A closing line such as Make second sleeve is also 2. When the section does not say how many to make, copies is null. Do not assume 1.

A method is how to knit a stitch or follow a chart, when the section is not one part of a garment. A numbered procedure, a tuck repeat, and a picture tutorial that casts on and knits are methods. A description of a chart that states the carriage setting, which needles knit, and how many passes make a knitted row is a method, even when the numbered steps are a different section.

procedure is true only when this section is the knitting: the rows, the needle selection, the repeats. It is true for a piece and for numbered steps. It is false for a chart description that does not itself give the steps, and false for notes, finishing, and page material.

A glossary is a list of abbreviations and what they mean. Return each token and its expansion. Prose that mentions a stitch is notes, not a glossary.

Gauge, sizes, yarn, and machine are that label. A sentence that mentions the machine, the yarn, or a size while describing the project does not make the section that kind. size_names are the size words in order, such as XS, S, M, or XS-M, L-2X, 3X-5X. A measurement line is not a size name. A piece that uses number groups stays a piece.

Finishing is seaming, wearing, blocking, or an edge treatment written after the pieces. How to Wrap is finishing. An unheaded paragraph that only says how to sew the pieces together is finishing. A bind-off that ends a piece stays in that piece.

Page is links to other patterns, a download or subscribe line, or a link onward to the next method. A section that is only links, such as a video, a shop, or the next page, is page, even when its heading says tips or notes. An opening that describes the garment is notes. An affiliate sentence inside a knitting section stays in that section.

heading is the heading or label copied from the section, or null when there is none. glossary is empty unless kind is glossary. size_names is empty unless kind is sizes. copies is null unless kind is piece and the section says how many to make.
"""

SCHEMA = _object(
    kind=_enum(SECTION_KINDS),
    heading=_nullable("string"),
    copies={"anyOf": [{"type": "null"}, {"type": "integer", "minimum": 1}]},
    procedure={"type": "boolean"},
    size_names={"type": "array", "items": {"type": "string"}},
    glossary={
        "type": "array",
        "items": _object(abbr={"type": "string"}, expansion={"type": "string"}),
    },
)


def run_section_parse(
    db: sqlite3.Connection,
    sections: tuple[Section, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
    on_section_ready=None,
) -> tuple[Section, ...]:
    """Parse each section and write that reading before the next section is read."""
    stored: list[Section] = []
    for index, section in enumerate(sections):
        if section.id is None:
            raise ParseFailure("The reading did not parse.")
        payload = complete(
            section.text,
            schema=SCHEMA,
            system=SYSTEM,
            reasoning_effort="low",
            schema_name="section",
            on_delta=on_delta,
        )
        saved = save_section_reading(db, _reading(section, payload))
        stored.append(saved)
        if on_section_ready is not None:
            on_section_ready(
                {
                    "index": index,
                    "kind": saved.kind,
                    "heading": saved.heading,
                    "copies": saved.copies,
                    "procedure": saved.procedure,
                }
            )
    return tuple(stored)


def _reading(section: Section, payload: object) -> Section:
    if type(payload) is not dict:
        raise ParseFailure("The reading did not parse.")
    kind = payload.get("kind")
    if kind not in SECTION_KINDS:
        raise ParseFailure("The reading did not parse.")
    procedure = payload.get("procedure")
    if type(procedure) is not bool:
        raise ParseFailure("The reading did not parse.")
    heading = _heading(payload.get("heading"))
    copies = payload.get("copies") if kind == "piece" else None
    if copies is not None and type(copies) is not int:
        raise ParseFailure("The reading did not parse.")
    try:
        return Section(
            text=section.text,
            id=section.id,
            kind=kind,
            heading=heading,
            copies=copies,
            procedure=procedure,
            size_names=_size_names(payload.get("size_names")) if kind == "sizes" else (),
            glossary=_glossary(payload.get("glossary")) if kind == "glossary" else (),
        )
    except (TypeError, ValueError) as exc:
        raise ParseFailure("The reading did not parse.") from exc


def _heading(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ParseFailure("The reading did not parse.")
    text = value.strip()
    return text or None


def _size_names(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise ParseFailure("The reading did not parse.")
    names: list[str] = []
    for item in value:
        if type(item) is not str or not item.strip():
            raise ParseFailure("The reading did not parse.")
        names.append(item.strip())
    return tuple(names)


def _glossary(value: object) -> tuple[Abbreviation, ...]:
    if type(value) is not list:
        raise ParseFailure("The reading did not parse.")
    terms: list[Abbreviation] = []
    for item in value:
        if type(item) is not dict:
            raise ParseFailure("The reading did not parse.")
        abbr = item.get("abbr")
        expansion = item.get("expansion")
        if type(abbr) is not str or type(expansion) is not str:
            raise ParseFailure("The reading did not parse.")
        if not abbr.strip() or not expansion.strip():
            raise ParseFailure("The reading did not parse.")
        terms.append(Abbreviation(abbr=abbr.strip(), expansion=expansion.strip()))
    return tuple(terms)
