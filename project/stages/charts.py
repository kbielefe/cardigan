"""Chart grids to passes stage."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from project import domain
from project.complete import OnDelta, _object, pass_schema
from project.model import Abbreviation, Pass, Piece, Repeat, Size
from project.parse import build_size_passes
from project.stages.call import StageComplete
from project.stages.sizes import _vocab_block

_BASE = pass_schema()
SCHEMA = _object(
    piece={"type": "string"},
    size={"type": "string"},
    passes=_BASE["properties"]["passes"],
    repeats=_BASE["properties"]["repeats"],
)

SYSTEM = """Turn this color chart grid into carriage passes for the matching piece and size.

The grid is row-major from the bottom of a fairisle chart unless labels say otherwise. Marked squares are needles to pull. Use the shared actions only. Each pass cites an exact span from the labels or nearby reading when possible; otherwise cite the shortest nearby label text.

Return the piece and size names that this chart belongs to, plus passes and repeats.
"""

POOL = 4


def run_charts(
    reading: str,
    charts: list[dict],
    pieces: tuple[Piece, ...],
    sizes_by_piece: dict[int, tuple[Size, ...]],
    abbreviations: tuple[Abbreviation, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> dict[int, tuple[tuple[Pass, ...], tuple[Repeat, ...]]]:
    """Return size_id -> chart passes to merge (append) into that size."""
    if not charts:
        return {}
    shared = domain.inject("Charts", "Fair isle")
    symbols = domain.stitch_symbols()
    vocab = _vocab_block(abbreviations)
    system = SYSTEM if not shared else f"{SYSTEM}\n\n{shared}"
    if symbols:
        system = f"{system}\n\nStitch symbol reference (excerpt):\n{symbols[:4000]}"
    if vocab:
        system = f"{system}\n\n{vocab}"

    size_index = _size_index(pieces, sizes_by_piece)

    def one(chart: dict):
        labels = chart.get("labels") or ""
        grid = chart.get("grid")
        colors = chart.get("colors") or {}
        content = {
            "labels": labels,
            "grid": grid,
            "colors": colors,
            "reading": reading,
            "pieces": [
                {
                    "name": piece.name,
                    "sizes": [size.name for size in sizes_by_piece.get(piece.id or -1, ())],
                }
                for piece in pieces
                if piece.parsed
            ],
        }
        payload = complete(
            json.dumps(content),
            schema=SCHEMA,
            system=system,
            reasoning_effort="high",
            schema_name="charts",
            on_delta=on_delta,
        )
        piece_name = payload.get("piece")
        size_name = payload.get("size")
        try:
            passes, repeats = build_size_passes(reading, payload)
        except (TypeError, ValueError):
            passes, repeats = (), ()
        key = None
        if type(piece_name) is str and type(size_name) is str:
            key = size_index.get((piece_name.strip().casefold(), size_name.strip().casefold()))
        return key, passes, repeats

    merged: dict[int, tuple[tuple[Pass, ...], tuple[Repeat, ...]]] = {}
    with ThreadPoolExecutor(max_workers=min(POOL, len(charts))) as pool:
        futures = [pool.submit(one, chart) for chart in charts]
        for future in as_completed(futures):
            size_id, passes, repeats = future.result()
            if size_id is None or not passes:
                continue
            prior = merged.get(size_id, ((), ()))
            offset = len(prior[0])
            shifted = tuple(
                Repeat(first=repeat.first + offset, last=repeat.last + offset, times=repeat.times)
                for repeat in repeats
            )
            merged[size_id] = (prior[0] + passes, prior[1] + shifted)
    return merged


def _size_index(
    pieces: tuple[Piece, ...],
    sizes_by_piece: dict[int, tuple[Size, ...]],
) -> dict[tuple[str, str], int]:
    index: dict[tuple[str, str], int] = {}
    for piece in pieces:
        if piece.id is None:
            continue
        for size in sizes_by_piece.get(piece.id, ()):
            if size.id is None:
                continue
            index[(piece.name.casefold(), size.name.casefold())] = size.id
    return index
