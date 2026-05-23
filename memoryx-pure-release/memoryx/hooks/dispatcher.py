from __future__ import annotations

from ..events import EventHandler, MemoryEvent, MiddlewareHandler


class EventDispatcher:
    def __init__(self) -> None:
        self._middleware: list[MiddlewareHandler] = []

    def inject_middleware(self, middleware: MiddlewareHandler) -> None:
        self._middleware.append(middleware)

    async def dispatch(self, event: MemoryEvent) -> MemoryEvent:
        current = event
        for mw in self._middleware:
            current = await mw(current)
        return current

    def middleware(self, next_handler: EventHandler):
        async def wrapped(*args, **kwargs):
            await next_handler(*args, **kwargs)
        return wrapped
