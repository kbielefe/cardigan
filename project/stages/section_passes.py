"""Turn one knitting section into carriage passes for every size."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from project.complete import OnDelta, _object, pass_schema
from project.model import Abbreviation, Pass, Piece, Section, Size
from project.parse import ParseFailure, build_size_passes
from project.stages.call import OnPieceReady, StageComplete
from project.store import save_piece

SYSTEM = """Turn this one section of a machine knitting pattern into carriage passes for every size.

Return one size for each size name, in the order given. The passes are the same trips, in the same order, for every size. count is the number at that size's place. A number written once is that count for every size. When no size names are given, return one size and name it from the heading, or one when the heading is none.

A number group lines up with the size names. The first number may stand alone, the next sizes sit in parentheses, and the largest sit in square brackets. That is one group. Use the number at that size's place. Do not subtract it from another number. A group whose length does not match the size names is not a size count. A parenthesis full of words, such as (make 2), is not a size. A measurement is not a count of rows.

A pass is one setup or one trip. Use the shared actions. Do not name a machine, a needle letter, a lever, or a tension dial.

kind setup is a sentence that only sets the carriage, resets the row counter, or only pulls needles out. It is not a trip, and its count is 1. kind trip is one carriage pass. "Knit N rows" and "K N rows" are one trip, and count is N for that size. Consecutive identical trips are one pass with a count. Several actions in one paragraph are several passes.

cite is an exact span of this section, copied unchanged. The same cite is used for that pass in every size. Prose between trips can stay uncited. Joining the cites does not have to reproduce the section.

carriage_end is left, right, or either only when the words name where the carriage is or which way it travels. Carriage on the right, COR, and "to the right" are right. COL and "to the left" are left. "Moved both ways" is the setting, not an end. A side of the bed named for the needles is a selection, not a carriage end. A trip with no end named has a null carriage end. Do not fill one in.

row_counter reset is RC 000, RC reset to 000, or row counter set to 000. checkpoint is an RC value after a block. target is knit to row N or knit to RC N. An RC line that is only the counter is its own setup. An RC value on the same line as a knit stays on that trip.

A repeat's first and last are the indexes of the passes inside the asterisks, for this size. The repeat sentence is not a pass. "For a total of N" and "N times worked" include the first time, so times is N. "N more times" is the first time plus N. When that number is 1, or the words give no number, omit the repeat for that size. The RC checkpoint after the repeat is its own pass, outside the repeat.

When the words do not settle a point, leave it open. An extra needle with no side named uses open_point extra_needle_side, method extra, count 1, and side null. Do not choose a side. method extra is only that one additional needle on an odd cast-on. N more needles, and a count of needles at the center, are stitch_count. Do not mark those with extra_needle_side.

On a selection, set only the fields that method uses, and null the rest. stitch_count uses count. each_side uses count and may use side. extra uses count and may use side. every_nth uses every, and uses needles_between and between_role together when needles are left between. needle_number uses needle. side uses side. edge may use count and side. all uses none of them.

Pull out to hold is role holding. Needles left in working position are role working. Every Nth needle, leaving some between, is every_nth. Edge needles are edge. A count of stitches is stitch_count. A count on each side of the bed is each_side. The whole of one side of the bed is side. All needles is all. Needles chosen from a chart, with no needle numbers in the words, are a setup with no selection rows.

Settings: plain when the needles knit and no lever is named. slip when side levers are on the dot or the circle, or the cam is set to slip. hold when the carriage is set not to knit the needles in hold, or Russell lever I, or part buttons. knit_holding when the holding needles are knit back, Russell lever II, or the words knit all needles. tuck when the yarn lays on the needles in hold for several passes. Scope is both when the words say both levers. Do not store the word Russell, Russel, or a letter such as D.

Shapes: an e-wrap or ewrap cast on is cast_on with technique e-wrap. Waste yarn and ravel cord stay inside that cite. A sentence that only says how those needles are divided stays inside that cite. A hand transfer written as a rib is transfer, not a ribber. Increase, decrease, short-row wrap of the first unworked needle, and bind off are those shapes. A sentence that only shapes is a setup. A decrease or increase written with a knit stays on that trip. technique is null except on an e-wrap cast on.

Yarn in the carriage is place main, and the name is the letter or name in the words. A tension number is not a pass. An affiliate line, a shop link, and a sentence about winding yarn or the extension beds are not passes. A closing line such as Make second sleeve is copies, already given, and is not a pass. Finishing written after the bind-off, such as an i-cord edging, is not a pass. Begin Neck Shaping stays in this section. The second side's row-counter reset is a setup. "Repeat the instructions" repeats the passes it names. Repeats cannot nest, so when those passes already contain a repeat, write the passes again after the second side's setup. The sentences after that, including the bind-off and any neckline, are still passes.

A mark such as mark edge stitches is a mark on the pass the words attach it to. It is not its own trip. When the section says two passes complete one knitted row, keep both trips.
"""


def _schema() -> dict:
    size = pass_schema()
    size["properties"] = {"name": {"type": "string"}, **size["properties"]}
    size["required"] = ["name", *size["required"]]
    return _object(sizes={"type": "array", "items": size})


SCHEMA = _schema()


def request_text(
    *,
    kind: str,
    heading: str | None,
    copies: int | None,
    size_names: tuple[str, ...] | list[str],
    glossary: tuple[Abbreviation, ...] | list,
    text: str,
) -> str:
    names = tuple(size_names)
    lines = [
        f"Kind: {kind}",
        f"Heading: {heading.strip() if type(heading) is str and heading.strip() else 'none'}",
    ]
    if kind == "piece":
        lines.append(f"Copies: {copies if copies is not None else 'unspecified'}")
    lines.append(f"Size count: {len(names) or 1}")
    lines.append("Size names: " + (", ".join(names) if names else "none"))
    terms = _terms(glossary)
    if terms:
        lines.append("Glossary:")
        lines.extend(f"{abbr} = {expansion}" for abbr, expansion in terms)
    else:
        lines.append("Glossary: none")
    if names:
        lines.append(f"Return {len(names)} sizes, in this order: {', '.join(names)}.")
    else:
        lines.append("Return 1 size.")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def build_sizes(
    text: str,
    payload: object,
    size_names: tuple[str, ...] | list[str],
    heading: str | None,
) -> tuple[Size, ...]:
    """One size per name. Counts are that size's integers. Cites are spans of ``text``."""
    if type(payload) is not dict:
        raise ParseFailure("The reading did not parse.")
    raw = payload.get("sizes")
    if type(raw) is not list or not raw or any(type(item) is not dict for item in raw):
        raise ParseFailure("The reading did not parse.")
    names = tuple(size_names)
    if names:
        if len(raw) != len(names):
            raise ParseFailure("The reading did not parse.")
    else:
        if len(raw) != 1:
            raise ParseFailure("The reading did not parse.")
        names = (_single_name(heading),)
    sizes: list[Size] = []
    for name, item in zip(names, raw):
        try:
            passes, repeats = build_size_passes(text, _without_single_repeats(item))
            sizes.append(Size(name=name, passes=passes, repeats=repeats))
        except (TypeError, ValueError) as exc:
            raise ParseFailure("The reading did not parse.") from exc
    _same_frames(sizes)
    return tuple(sizes)


def run_section_passes(
    db: sqlite3.Connection,
    project_id: int,
    reading: str,
    sections: tuple[Section, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
    on_piece_ready: OnPieceReady | None = None,
) -> tuple[Piece, ...]:
    """Write each knitting section's passes before the next knitting section is read."""
    if "".join(section.text for section in sections) != reading:
        raise ParseFailure("The reading did not parse.")
    size_names = tuple(name for section in sections if section.kind == "sizes" for name in section.size_names)
    glossary = tuple(term for section in sections if section.kind == "glossary" for term in section.glossary)
    stored: list[Piece] = []
    offset = 0
    for section in sections:
        if _knitting(section):
            payload = complete(
                request_text(
                    kind=section.kind or "",
                    heading=section.heading,
                    copies=section.copies,
                    size_names=size_names,
                    glossary=glossary,
                    text=section.text,
                ),
                schema=SCHEMA,
                system=SYSTEM,
                reasoning_effort="low",
                schema_name="section_passes",
                on_delta=on_delta,
            )
            sizes = _shift(build_sizes(section.text, payload, size_names, section.heading), offset)
            piece = Piece(name=_piece_name(section), copies=section.copies or 1, sizes=sizes)
            saved = save_piece(db, project_id, piece)
            stored.append(saved)
            if on_piece_ready is not None:
                for size in saved.sizes:
                    on_piece_ready({"piece": saved.name, "size": size.name, "pass_count": len(size.passes)})
        offset += len(section.text)
    return tuple(stored)


def _knitting(section: Section) -> bool:
    return section.kind in {"piece", "method"} and section.procedure is True


def _piece_name(section: Section) -> str:
    if type(section.heading) is str and section.heading.strip():
        return section.heading.strip()
    return "Piece" if section.kind == "piece" else "Method"


def _single_name(heading: str | None) -> str:
    if type(heading) is str and heading.strip():
        return heading.strip()
    return "one"


def _terms(glossary: tuple[Abbreviation, ...] | list) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    for item in glossary:
        if type(item) is dict:
            abbr = item.get("abbr")
            expansion = item.get("expansion")
        else:
            abbr = item.abbr
            expansion = item.expansion
        if type(abbr) is str and type(expansion) is str and abbr.strip() and expansion.strip():
            terms.append((abbr.strip(), expansion.strip()))
    return terms


def _without_single_repeats(item: dict) -> dict:
    raw = item.get("repeats")
    if raw is None:
        return item
    if type(raw) is not list:
        raise ParseFailure("The reading did not parse.")
    kept = []
    for repeat in raw:
        if type(repeat) is not dict:
            raise ParseFailure("The reading did not parse.")
        times = repeat.get("times")
        if type(times) is not int:
            raise ParseFailure("The reading did not parse.")
        if times < 2:
            continue
        kept.append(repeat)
    return {**item, "repeats": kept}


def _same_frames(sizes: list[Size]) -> None:
    first = sizes[0]
    for size in sizes[1:]:
        if len(size.passes) != len(first.passes):
            raise ParseFailure("The reading did not parse.")
        for left, right in zip(first.passes, size.passes):
            if left.kind != right.kind or (left.cite_start, left.cite_end) != (right.cite_start, right.cite_end):
                raise ParseFailure("The reading did not parse.")


def _shift(sizes: tuple[Size, ...], offset: int) -> tuple[Size, ...]:
    if offset == 0:
        return sizes
    shifted: list[Size] = []
    for size in sizes:
        passes = tuple(_shift_pass(step, offset) for step in size.passes)
        shifted.append(replace(size, passes=passes))
    return tuple(shifted)


def _shift_pass(step: Pass, offset: int) -> Pass:
    return replace(step, cite_start=step.cite_start + offset, cite_end=step.cite_end + offset)
