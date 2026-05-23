from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

from ..events import EventHandler, EventPriority, MemoryEvent, MemoryEventType, MiddlewareHandler
from .dead_letter_queue import DeadLetterQueue
from .dispatcher import EventDispatcher
from .health_monitor import HealthMonitor
from .queue_manager import QueueManager
from .retry_manager import RetryManager
from .session_listener import SessionEventListener
from .subscriber_manager import SubscriberManager


class MemoryHookManager:
    def __init__(self, settings, logger, retries: int | None = None) -> None:
        self.settings = settings
        self.logger = logger
        self.subscribers = SubscriberManager()
        self.dispatcher = EventDispatcher()
        self.queue_mgr = QueueManager(
            queue_dir=self.settings.event_queue_dir,
            queue_size=self.settings.queue_size,
            enqueue_timeout=self.settings.enqueue_timeout_seconds,
        )
        self.retry_mgr = RetryManager(
            retries=retries if retries is not None else settings.retry_attempts,
            base_delay=settings.retry_base_delay,
            max_delay=settings.retry_max_delay,
            timeout=settings.handler_timeout_seconds,
        )
        self.dlq = DeadLetterQueue(self.settings.dead_letters_dir)
        self.health = HealthMonitor()
        self._workers: list[asyncio.Task] = []
        self._closed = asyncio.Event()
        self._plugins: dict[str, tuple[str, EventHandler, MemoryEventType]] = {}
        self._listener = SessionEventListener(self)

    async def start(self) -> None:
        if self._workers:
            return
        self.settings.ensure_directories()
        for recovered in await self.queue_mgr.recover():
            self.queue_mgr.put_nowait(recovered)
        self.logger.info(
            "memoryx.manager_starting",
            workers=self.settings.workers,
            queue_size=self.settings.queue_size,
        )
        for _ in range(self.settings.workers):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        self._closed.set()
        for _ in self._workers:
            try:
                self.queue_mgr.put_nowait(None)
            except asyncio.QueueFull:
                break
        if self._workers:
            await asyncio.wait_for(
                asyncio.gather(*self._workers, return_exceptions=True),
                timeout=self.settings.drain_timeout_seconds,
            )
        self._workers.clear()
        self.logger.info("memoryx.manager_stopped")

    async def emit(self, event_type: MemoryEventType, session_id: Optional[str], payload: dict) -> None:
        trace_id = str(payload.pop("trace_id", "") or "")
        kwargs: dict[str, Any] = {"event_type": event_type, "session_id": session_id, "payload": payload}
        if trace_id:
            kwargs["trace_id"] = trace_id
        event = MemoryEvent(**kwargs)
        event = await self.dispatcher.dispatch(event)
        await self.queue_mgr.persist(event)
        if self._should_warn_backpressure():
            self.logger.warning(
                "memoryx.queue_pressure",
                current_size=self.queue_mgr.depth(),
                max_size=self.queue_mgr.maxsize(),
            )
        try:
            self.queue_mgr.put_nowait(event)
        except asyncio.QueueFull:
            if self.queue_mgr.can_drop(event):
                self.health.record_drop()
                await self.queue_mgr.delete(event.event_id)
                return
            await self.queue_mgr.put(event)

    async def register_handler(
        self,
        event_type: MemoryEventType,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        self.subscribers.subscribe(event_type, handler, priority=priority)

    async def unregister_handler(self, event_type: MemoryEventType, handler: EventHandler) -> None:
        self.subscribers.unsubscribe(event_type, handler)

    async def register_plugin(
        self,
        name: str,
        event_type: MemoryEventType,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        await self.register_handler(event_type, handler, priority=priority)
        self._plugins[name] = (name, handler, event_type)

    async def inject_middleware(self, middleware: MiddlewareHandler) -> None:
        self.dispatcher.inject_middleware(middleware)

    async def dispatch(self, event: MemoryEvent) -> MemoryEvent:
        return await self.dispatcher.dispatch(event)

    @property
    def listener(self) -> SessionEventListener:
        return self._listener

    def queue_depth(self) -> int:
        return self.queue_mgr.depth()

    def health_metrics(self) -> dict:
        return self.health.metrics(
            queue_depth=self.queue_mgr.depth(),
            queue_maxsize=self.queue_mgr.maxsize(),
            worker_count=len(self._workers),
            **self.retry_mgr.metrics(),
        )

    def middleware(self, next_handler: Callable[..., Awaitable[None]]):
        async def wrapped(*args, **kwargs):
            await next_handler(*args, **kwargs)
        return wrapped

    def _should_warn_backpressure(self) -> bool:
        if self.queue_mgr.maxsize() <= 0:
            return False
        return (self.queue_mgr.depth() / self.queue_mgr.maxsize()) >= self.settings.queue_warning_threshold

    async def _worker(self) -> None:
        while not self._closed.is_set() or self.queue_mgr.depth() > 0:
            event = await self.queue_mgr.get()
            started = time.perf_counter()
            try:
                if event is None:
                    return
                handlers = self.subscribers.handlers(event.event_type)
                for handler in handlers:
                    try:
                        await self.retry_mgr.run(handler, event)
                    except Exception as exc:
                        await self.dlq.write(event, str(exc))
                        self.logger.error(
                            "memoryx.handler_failed",
                            event_type=event.event_type,
                            session_id=event.session_id,
                            event_id=event.event_id,
                            trace_id=event.trace_id,
                            error=str(exc),
                        )
                        # 隔离：一个 subscriber 失败不影响其他 subscriber
                        continue
                await self.queue_mgr.delete(event.event_id)
                self.health.record_event()
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.health.record_latency(elapsed_ms)
                self.queue_mgr.task_done()
