from __future__ import annotations

from .events import MemoryEventType

HOOK_EVENTS = [
    MemoryEventType.ON_USER_MESSAGE,
    MemoryEventType.ON_ASSISTANT_RESPONSE,
    MemoryEventType.ON_TOOL_CALL,
    MemoryEventType.ON_TOOL_RESULT,
    MemoryEventType.ON_SESSION_END,
]
