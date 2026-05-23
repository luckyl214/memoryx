from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class WorkingMemoryState:
    session_id: str
    current_task: str = ""
    reasoning_chain: list[str] = field(default_factory=list)
    active_todos: list[str] = field(default_factory=list)
    temporary_context: dict[str, Any] = field(default_factory=dict)
    debug_session: dict[str, Any] = field(default_factory=dict)
    workflow_state: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
