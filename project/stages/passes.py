"""Passes stage: extract passes for one size."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from project import domain
from project.complete import OnDelta, pass_schema
from project.model import Abbreviation, Pass, Piece, Repeat, Size
from project.parse import build_size_passes
from project.stages.call import OnPieceReady, StageComplete
from project.stages.sizes import _vocab_block

SYSTEM = """Turn these instruction sections into carriage passes for one size.

Use the shared actions only. Do not name a machine, a needle letter, or a lever.

A pass is one setup or one trip. Consecutive identical trips are one pass with a count. "Knit N rows" and "K N rows" are one trip. The count is the number for that size.

Each pass cites an exact span of the reading, copied unchanged. When the reading does not settle a point, leave it open. An extra needle with no side named uses open_point extra_needle_side and no side. A trip with no carriage end named has a null carriage end.
"""

POOL = 4


def run_passes(
    reading: str,
    pieces: tuple[Piece, ...],
    sizes_by_piece: dict[int, tuple[Size, ...]],
    sections_by_size: dict[int, list[str]],
    abbreviations: tuple[Abbreviation, ...],
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
    on_piece_ready: OnPieceReady | None = None,
) -> dict[int, tuple[tuple[Pass, ...], tuple[Repeat, ...]]]:
    """LLM calls in parallel; returns size_id -> (passes, repeats)."""
    shared = domain.inject("Shared actions", "A pass and a row")
    vocab = _vocab_block(abbreviations)
    system = SYSTEM if not shared else f"{SYSTEM}\n\n{shared}"
    if vocab:
        system = f"{system}\n\n{vocab}"

    jobs: list[tuple[int, str, str, str]] = []
    for piece in pieces:
        if not piece.parsed or piece.id is None:
            continue
        for size in sizes_by_piece.get(piece.id, ()):
            if size.id is None:
                continue
            sections = sections_by_size.get(size.id) or []
            body = "\n\n".join(sections) if sections else reading
            content = f"Piece: {piece.name}\nSize: {size.name}\n\nSections:\n{body}\n\nReading:\n{reading}"
            jobs.append((size.id, piece.name, size.name, content))

    results: dict[int, tuple[tuple[Pass, ...], tuple[Repeat, ...]]] = {}
    if not jobs:
        return results

    def one(job: tuple[int, str, str, str]):
        size_id, piece_name, size_name, content = job
        payload = complete(
            content,
            schema=pass_schema(),
            system=system,
            reasoning_effort="high",
            schema_name="passes",
            on_delta=on_delta,
        )
        try:
            passes, repeats = build_size_passes(reading, payload)
        except (TypeError, ValueError):
            passes, repeats = (), ()
        return size_id, piece_name, size_name, passes, repeats

    with ThreadPoolExecutor(max_workers=min(POOL, len(jobs))) as pool:
        futures = [pool.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            size_id, piece_name, size_name, passes, repeats = future.result()
            results[size_id] = (passes, repeats)
            if on_piece_ready is not None:
                on_piece_ready(
                    {
                        "piece": piece_name,
                        "size": size_name,
                        "pass_count": len(passes),
                    }
                )
    return results
