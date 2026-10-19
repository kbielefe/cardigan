"""Shared stage call shape."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from project.complete import OnDelta


class StageComplete(Protocol):
    def __call__(
        self,
        content: str,
        *,
        schema: dict,
        system: str,
        reasoning_effort: str = "medium",
        schema_name: str = "result",
        on_delta: OnDelta | None = None,
    ) -> dict: ...


OnStage = Callable[[str], None]
OnPieceReady = Callable[[dict], None]
OnSectionReady = Callable[[dict], None]
