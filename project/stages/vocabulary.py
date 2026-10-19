"""Vocabulary stage: abbreviations."""

from __future__ import annotations

import sqlite3

from project import domain
from project.complete import OnDelta, _object
from project.model import Abbreviation
from project.stages.call import StageComplete
from project.store import save_abbreviations

SYSTEM = f"""Extract the abbreviation glossary for this pattern.

Return each abbreviation and its expansion as used in this reading. Prefer definitions written in the pattern itself.

{domain.GLOSSARY_WINS}

When the pattern has no glossary entry for a token that appears in the reading, you may use the usual machine-knitting sense. Do not invent expansions for tokens that never appear.
"""

SCHEMA = _object(
    abbreviations={
        "type": "array",
        "items": _object(
            abbr={"type": "string"},
            expansion={"type": "string"},
        ),
    }
)


def run_vocabulary(
    db: sqlite3.Connection,
    project_id: int,
    reading: str,
    complete: StageComplete,
    *,
    on_delta: OnDelta | None = None,
) -> tuple[Abbreviation, ...]:
    hints = domain.abbreviations_in_text(reading)
    content = reading
    if hints:
        lines = "\n".join(f"{abbr} — {expansion}" for abbr, expansion in hints[:40])
        content = f"{reading}\n\nKnown reference abbreviations (pattern glossary wins):\n{lines}"
    payload = complete(
        content,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="vocabulary",
        on_delta=on_delta,
    )
    raw = payload.get("abbreviations")
    items: list[Abbreviation] = []
    if type(raw) is list:
        for item in raw:
            if type(item) is not dict:
                continue
            abbr = item.get("abbr")
            expansion = item.get("expansion")
            if type(abbr) is not str or type(expansion) is not str:
                continue
            if not abbr.strip() or not expansion.strip():
                continue
            try:
                items.append(Abbreviation(abbr=abbr.strip(), expansion=expansion.strip()))
            except ValueError:
                continue
    return save_abbreviations(db, project_id, tuple(items))
