from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ToolInteractionRecord:
    session_id: str
    tool_name: str
    action_type: str
    command: str
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
