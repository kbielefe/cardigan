"""Staged Accept parse: write to SQLite as each stage completes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from project.complete import OnDelta
from project.model import Project
from project.parse import ParseFailure
from project.stages import run_metadata
from project.stages.call import OnPieceReady, OnSectionReady, OnStage, StageComplete
from project.stages.section_parse import run_section_parse
from project.stages.split import run_split
from project.store import create_project, load_project


def run(
    reading: str,
    db: sqlite3.Connection,
    *,
    complete: StageComplete | Callable,
    charts: list | None = None,
    on_stage: OnStage | None = None,
    on_piece_ready: OnPieceReady | None = None,
    on_section_ready: OnSectionReady | None = None,
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

        emit("sections")
        sections = run_split(db, project_id, reading, complete, on_delta=on_delta)

        emit("section")
        run_section_parse(
            db,
            sections,
            complete,
            on_delta=on_delta,
            on_section_ready=on_section_ready,
        )

    except ParseFailure:
        raise
    except Exception as exc:
        raise ParseFailure("The model did not answer.") from exc

    return load_project(db, project_id)
