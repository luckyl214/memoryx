from __future__ import annotations

from ..events import EventHandler, EventPriority, MemoryEvent, MemoryEventType


class SubscriberManager:
    def __init__(self) -> None:
        self._subscribers: dict[MemoryEventType, list[tuple[EventHandler, EventPriority, int]]] = {}
        self._order = 0

    def subscribe(self, event_type: MemoryEventType, handler: EventHandler, priority: EventPriority = EventPriority.NORMAL) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if any(h == handler for h, _, _ in self._subscribers[event_type]):
            return
        self._subscribers[event_type].append((handler, priority, self._order))
        self._order += 1
        self._subscribers[event_type].sort(key=lambda item: (item[1], item[2]))

    def unsubscribe(self, event_type: MemoryEventType, handler: EventHandler) -> None:
        if event_type not in self._subscribers:
            return
        self._subscribers[event_type] = [(h, p, o) for h, p, o in self._subscribers[event_type] if h != handler]

    def handlers(self, event_type: MemoryEventType) -> list[EventHandler]:
        return [h for h, _, _ in self._subscribers.get(event_type, [])]

    def count(self, event_type: MemoryEventType) -> int:
        return len(self._subscribers.get(event_type, []))
