"""Sections stage: ordered cite spans per size (orchestration only)."""

from __future__ import annotations

from project import domain
from project.complete import OnDelta, _object
from project.model import Abbreviation, Piece, Size
from project.stages.call import StageComplete
from project.stages.sizes import _vocab_block

SYSTEM = """Split this piece and size into ordered instruction sections.

Each section is an exact cite span from the reading: a consecutive block of instructions for this size. Preserve reading order. Skip finishing, seaming, and blocking. Do not invent text.
"""

SCHEMA = _object(
    sections={
        "type": "array",
        "items": _object(cite={"type": "string"}),
    }
)


def run_sections(
    reading: str,
    pieces: tuple[Piece, ...],
    piece_cites: dict[int, str],
    sizes_by_piece: dict[int, tuple[Size, ...]],
    abbreviations: tuple[Abbreviation, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> dict[int, list[str]]:
    """Return size_id -> ordered cite strings."""
    extras = domain.inject("Repeats", "Sections of a pattern")
    vocab = _vocab_block(abbreviations)
    system = SYSTEM if not extras else f"{SYSTEM}\n\n{extras}"
    if vocab:
        system = f"{system}\n\n{vocab}"
    by_size: dict[int, list[str]] = {}
    for piece in pieces:
        if not piece.parsed or piece.id is None:
            continue
        sizes = sizes_by_piece.get(piece.id, ())
        cite = piece_cites.get(piece.id) or piece.name
        for size in sizes:
            if size.id is None:
                continue
            content = (
                f"Piece: {piece.name}\nSize: {size.name}\n\nPiece span:\n{cite}\n\nReading:\n{reading}"
            )
            payload = complete(
                content,
                schema=SCHEMA,
                system=system,
                reasoning_effort="medium",
                schema_name="sections",
                on_delta=on_delta,
            )
            raw = payload.get("sections")
            cites: list[str] = []
            if type(raw) is list:
                for item in raw:
                    if type(item) is not dict:
                        continue
                    quote = item.get("cite")
                    if type(quote) is str and quote:
                        cites.append(quote)
            if not cites and cite:
                cites = [cite]
            by_size[size.id] = cites
    return by_size
