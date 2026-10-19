"""Metadata stage: project name."""

from __future__ import annotations

import sqlite3

from project.complete import OnDelta, _object
from project.stages.call import StageComplete
from project.store import set_project_name

SYSTEM = """Name this knitting pattern from its frozen reading.

Return a short pattern name from the title or opening lines. Prefer the garment or pattern title over a site or shop name. If no title is clear, use a short descriptive name from the first piece heading.
"""

SCHEMA = _object(name={"type": "string"})


def run_metadata(
    db: sqlite3.Connection,
    project_id: int,
    reading: str,
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> str | None:
    payload = complete(
        reading,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="metadata",
        on_delta=on_delta,
    )
    name = payload.get("name")
    if type(name) is not str or not name.strip():
        return None
    name = name.strip()
    set_project_name(db, project_id, name)
    return name
