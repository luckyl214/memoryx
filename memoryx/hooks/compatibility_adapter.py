from __future__ import annotations

from ..events import MemoryEvent, MemoryEventType


class CompatibilityAdapter:
    @staticmethod
    def to_event(event_type: MemoryEventType, **payload) -> MemoryEvent:
        session_id = payload.pop("session_id", None)
        trace_id = str(payload.pop("trace_id", "") or "")
        kwargs = {"event_type": event_type, "session_id": session_id, "payload": payload}
        if trace_id:
            kwargs["trace_id"] = trace_id
        return MemoryEvent(**kwargs)

    @staticmethod
    def normalize_hook_event(hook_name: str) -> MemoryEventType | None:
        mapping = {
            "on_user_message": MemoryEventType.ON_USER_MESSAGE,
            "on_assistant_response": MemoryEventType.ON_ASSISTANT_RESPONSE,
            "on_tool_call": MemoryEventType.ON_TOOL_CALL,
            "on_tool_result": MemoryEventType.ON_TOOL_RESULT,
            "on_session_end": MemoryEventType.ON_SESSION_END,
        }
        return mapping.get(hook_name)
