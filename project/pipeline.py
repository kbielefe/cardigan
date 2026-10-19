"""Staged Accept parse: write to SQLite as each stage completes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from project.complete import OnDelta
from project.model import (
    CarriageSetting,
    Pass,
    Piece,
    Project,
    Repeat,
    Selection,
    Shape,
    Size,
    Yarn,
)
from project.parse import ParseFailure
from project.stages import (
    run_charts,
    run_metadata,
    run_passes,
    run_pieces,
    run_sections,
    run_sizes,
    run_vocabulary,
)
from project.stages.call import OnPieceReady, OnStage, StageComplete
from project.store import create_project, load_project, replace_pieces, replace_size_passes


def run(
    reading: str,
    db: sqlite3.Connection,
    *,
    complete: StageComplete | Callable,
    charts: list | None = None,
    on_stage: OnStage | None = None,
    on_piece_ready: OnPieceReady | None = None,
    on_delta: OnDelta | None = None,
) -> Project:
    if type(reading) is not str or not reading.strip():
        raise ParseFailure("The reading did not parse.")
    charts = list(charts or [])

    def emit(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    emit("bootstrap")
    project = create_project(db, reading)
    assert project.id is not None
    project_id = project.id

    try:
        emit("metadata")
        run_metadata(db, project_id, reading, complete, on_delta=on_delta)

        emit("pieces")
        pieces, piece_cites = run_pieces(db, project_id, reading, complete, on_delta=on_delta)

        emit("vocabulary")
        abbreviations = run_vocabulary(db, project_id, reading, complete, on_delta=on_delta)

        emit("sizes")
        sizes_by_piece = run_sizes(
            db, reading, pieces, piece_cites, abbreviations, complete, on_delta=on_delta
        )

        emit("sections")
        sections_by_size = run_sections(
            reading, pieces, piece_cites, sizes_by_piece, abbreviations, complete, on_delta=on_delta
        )

        emit("passes")
        pass_results = run_passes(
            reading,
            pieces,
            sizes_by_piece,
            sections_by_size,
            abbreviations,
            complete,
            on_delta=on_delta,
            on_piece_ready=on_piece_ready,
        )

        chart_results: dict[int, tuple[tuple[Pass, ...], tuple[Repeat, ...]]] = {}
        if charts:
            emit("charts")
            chart_results = run_charts(
                reading,
                charts,
                pieces,
                sizes_by_piece,
                abbreviations,
                complete,
                on_delta=on_delta,
            )

        for size_id, (passes, repeats) in pass_results.items():
            chart = chart_results.pop(size_id, None)
            if chart is not None:
                offset = len(passes)
                chart_passes, chart_repeats = chart
                shifted = tuple(
                    Repeat(first=item.first + offset, last=item.last + offset, times=item.times)
                    for item in chart_repeats
                )
                passes = passes + chart_passes
                repeats = repeats + shifted
            replace_size_passes(db, size_id, passes, repeats)

        for size_id, (passes, repeats) in chart_results.items():
            replace_size_passes(db, size_id, passes, repeats)

        _demote_empty_pieces(db, project_id)

    except ParseFailure:
        raise
    except Exception as exc:
        raise ParseFailure("The model did not answer.") from exc

    return load_project(db, project_id)


def _demote_empty_pieces(db: sqlite3.Connection, project_id: int) -> None:
    """A parsed piece with no passes in any size becomes unparsed."""
    project = load_project(db, project_id)
    if not any(piece.parsed and not any(size.passes for size in piece.sizes) for piece in project.pieces):
        return
    fresh: list[Piece] = []
    for piece in project.pieces:
        if piece.parsed and not any(size.passes for size in piece.sizes):
            fresh.append(Piece(name=piece.name, copies=piece.copies, parsed=False))
            continue
        fresh.append(
            Piece(
                name=piece.name,
                copies=piece.copies,
                parsed=piece.parsed,
                sizes=tuple(_fresh_size(size) for size in piece.sizes),
            )
        )
    replace_pieces(db, project_id, tuple(fresh))


def _fresh_size(size: Size) -> Size:
    return Size(
        name=size.name,
        passes=tuple(_fresh_pass(step) for step in size.passes),
        repeats=tuple(Repeat(first=item.first, last=item.last, times=item.times) for item in size.repeats),
    )


def _fresh_pass(step: Pass) -> Pass:
    return Pass(
        kind=step.kind,
        cite_start=step.cite_start,
        cite_end=step.cite_end,
        count=step.count,
        carriage_end=step.carriage_end,
        row_counter=step.row_counter,
        open_point=step.open_point,
        selections=tuple(
            Selection(
                role=item.role,
                method=item.method,
                count=item.count,
                every=item.every,
                needles_between=item.needles_between,
                between_role=item.between_role,
                needle=item.needle,
                side=item.side,
            )
            for item in step.selections
        ),
        settings=tuple(CarriageSetting(name=item.name, scope=item.scope) for item in step.settings),
        shapes=tuple(Shape(name=item.name, count=item.count, technique=item.technique) for item in step.shapes),
        yarns=tuple(Yarn(place=item.place, name=item.name) for item in step.yarns),
        mark=step.mark,
    )
