from __future__ import annotations

from ..events import MemoryEvent, MemoryEventType


class HermesCompatibilityAdapter:
    def to_event(self, event_type: MemoryEventType, **payload) -> MemoryEvent:
        session_id = payload.pop("session_id", None)
        trace_id = str(payload.pop("trace_id", "") or "")
        kwargs = {"event_type": event_type, "session_id": session_id, "payload": payload}
        if trace_id:
            kwargs["trace_id"] = trace_id
        return MemoryEvent(**kwargs)
