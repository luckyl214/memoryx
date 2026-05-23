from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from memoryx.config import MemoryXSettings
from memoryx.events import MemoryEvent, MemoryEventType
from memoryx.logging import configure_logging, get_logger
from memoryx.manager import MemoryHookManager


def _settings() -> MemoryXSettings:
    return MemoryXSettings(home=Path(tempfile.mkdtemp(prefix="memoryx-hook-")), queue_size=16, workers=1)


@pytest.mark.asyncio
async def test_queue_dispatch_and_handler():
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    logger = get_logger("test")
    manager = MemoryHookManager(settings=settings, logger=logger)

    seen = []

    async def handler(event):
        seen.append((event.event_type, event.payload["content"]))

    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, handler)
    await manager.start()
    await manager.emit(MemoryEventType.ON_USER_MESSAGE, "s1", {"content": "hello"})
    await asyncio.sleep(0.05)
    await manager.stop()

    assert seen == [(MemoryEventType.ON_USER_MESSAGE, "hello")]


@pytest.mark.asyncio
async def test_retry_on_failure():
    settings = _settings().model_copy(update={"retry_attempts": 2})
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    logger = get_logger("test")
    manager = MemoryHookManager(settings=settings, logger=logger)

    calls = 0

    async def flaky(event):
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RuntimeError("boom")

    await manager.register_handler(MemoryEventType.ON_SESSION_END, flaky)
    await manager.start()
    await manager.emit(MemoryEventType.ON_SESSION_END, "s1", {})
    await asyncio.sleep(0.1)
    await manager.stop()

    assert calls == 2


@pytest.mark.asyncio
async def test_middleware_dispatch_mutates_event_payload():
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    logger = get_logger("test")
    manager = MemoryHookManager(settings=settings, logger=logger)

    seen = []

    async def middleware(event: MemoryEvent) -> MemoryEvent:
        event.payload["middleware_seen"] = True
        return event

    async def handler(event: MemoryEvent):
        seen.append(event.payload["middleware_seen"])

    await manager.inject_middleware(middleware)
    await manager.register_handler(MemoryEventType.ON_TOOL_CALL, handler)
    await manager.start()
    await manager.emit(MemoryEventType.ON_TOOL_CALL, "s1", {"tool_name": "rg", "args": {}})
    await asyncio.sleep(0.05)
    await manager.stop()

    assert seen == [True]


@pytest.mark.asyncio
async def test_plugin_registration_tracks_handler():
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    logger = get_logger("test")
    manager = MemoryHookManager(settings=settings, logger=logger)

    async def handler(event: MemoryEvent):
        return None

    await manager.register_plugin("example", MemoryEventType.ON_SESSION_END, handler)

    assert "example" in manager._plugins
