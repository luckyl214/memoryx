from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TemporalState:
    memory_id: str
    content: str
    version_number: int
    valid_from: str | None = None
    valid_to: str | None = None
    active_state: int = 1
    superseded_by: str | None = None
