from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryEventType(StrEnum):
    ON_USER_MESSAGE = "on_user_message"
    ON_ASSISTANT_RESPONSE = "on_assistant_response"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
    ON_SESSION_END = "on_session_end"


class EventPriority(IntEnum):
    CRITICAL = 0
    HIGH = 10
    NORMAL = 20
    LOW = 30
    BACKGROUND = 40


_PRIORITY_BY_EVENT_TYPE = {
    MemoryEventType.ON_USER_MESSAGE: EventPriority.CRITICAL,
    MemoryEventType.ON_SESSION_END: EventPriority.CRITICAL,
    MemoryEventType.ON_TOOL_CALL: EventPriority.HIGH,
    MemoryEventType.ON_ASSISTANT_RESPONSE: EventPriority.NORMAL,
    MemoryEventType.ON_TOOL_RESULT: EventPriority.LOW,
}


class MemoryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: MemoryEventType
    event_version: str = "1.0"
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    priority: EventPriority | None = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    attempt: int = 0
    dropped: bool = False

    def model_post_init(self, __context: Any) -> None:
        if self.priority is None:
            self.priority = _PRIORITY_BY_EVENT_TYPE.get(self.event_type, EventPriority.NORMAL)


EventHandler = Callable[[MemoryEvent], Awaitable[None]]
MiddlewareHandler = Callable[[MemoryEvent], Awaitable[MemoryEvent]]
