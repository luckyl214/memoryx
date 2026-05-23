from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import DefaultDict
from collections import defaultdict

from .events import EventHandler, EventPriority, MemoryEvent, MemoryEventType


@dataclass(slots=True)
class Subscriber:
    handler: EventHandler
    priority: EventPriority
    order: int


class EventBus:
    def __init__(self) -> None:
        self._handlers: DefaultDict[MemoryEventType, list[Subscriber]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._order = 0

    async def subscribe(
        self,
        event_type: MemoryEventType,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        async with self._lock:
            if any(item.handler == handler for item in self._handlers[event_type]):
                return
            self._handlers[event_type].append(Subscriber(handler=handler, priority=priority, order=self._order))
            self._order += 1
            self._handlers[event_type].sort(key=lambda item: (item.priority, item.order))

    async def unsubscribe(self, event_type: MemoryEventType, handler: EventHandler) -> None:
        async with self._lock:
            handlers = self._handlers.get(event_type, [])
            self._handlers[event_type] = [item for item in handlers if item.handler != handler]

    async def publish(self, event: MemoryEvent) -> list[EventHandler]:
        async with self._lock:
            return [item.handler for item in self._handlers.get(event.event_type, [])]

    async def handler_count(self, event_type: MemoryEventType) -> int:
        async with self._lock:
            return len(self._handlers.get(event_type, []))
