from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from memoryx.config import MemoryXSettings
from memoryx.events import EventPriority, MemoryEvent, MemoryEventType
from memoryx.logging import configure_logging, get_logger
from memoryx.manager import MemoryHookManager
from memoryx.hermes_adapter import HermesCompatibilityAdapter


def _settings() -> MemoryXSettings:
    return MemoryXSettings(home=Path(tempfile.mkdtemp(prefix="memoryx-hook15-")), queue_size=16, workers=1)


def test_event_contract_has_version_trace_and_priority() -> None:
    event = MemoryEvent(event_type=MemoryEventType.ON_USER_MESSAGE, session_id="s1", payload={"content": "hello"})

    assert event.event_version == "1.0"
    assert event.trace_id
    assert event.priority == EventPriority.CRITICAL
    assert event.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_trace_id_propagates_from_listener_payload() -> None:
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    manager = MemoryHookManager(settings=settings, logger=get_logger("test"))
    seen: list[str] = []

    async def handler(event: MemoryEvent) -> None:
        seen.append(event.trace_id)

    await manager.register_handler(MemoryEventType.ON_TOOL_CALL, handler)
    await manager.start()
    await manager.listener.on_tool_call("s1", "rg", {}, trace_id="trace-123")
    await asyncio.sleep(0.05)
    await manager.stop()

    assert seen == ["trace-123"]


@pytest.mark.asyncio
async def test_priority_handlers_run_before_background_handlers() -> None:
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    manager = MemoryHookManager(settings=settings, logger=get_logger("test"))
    order: list[str] = []

    async def low_handler(event: MemoryEvent) -> None:
        order.append("low")

    async def critical_handler(event: MemoryEvent) -> None:
        order.append("critical")

    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, low_handler, priority=EventPriority.BACKGROUND)
    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, critical_handler, priority=EventPriority.CRITICAL)
    await manager.start()
    await manager.emit(MemoryEventType.ON_USER_MESSAGE, "s1", {"content": "hello"})
    await asyncio.sleep(0.05)
    await manager.stop()

    assert order == ["critical", "low"]


@pytest.mark.asyncio
async def test_dead_letter_queue_is_written_when_handler_exhausts_retries() -> None:
    settings = _settings().model_copy(update={"retry_attempts": 1})
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    manager = MemoryHookManager(settings=settings, logger=get_logger("test"))

    async def broken(event: MemoryEvent) -> None:
        raise RuntimeError("bad payload")

    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, broken)
    await manager.start()
    await manager.emit(MemoryEventType.ON_USER_MESSAGE, "s1", {"content": "hello"})
    await asyncio.sleep(0.05)
    await manager.stop()

    letters = list(settings.dead_letters_dir.glob("*.json"))
    assert len(letters) == 1
    payload = json.loads(letters[0].read_text(encoding="utf-8"))
    assert payload["event"]["event_type"] == "on_user_message"
    assert payload["error"] == "bad payload"


@pytest.mark.asyncio
async def test_event_persistence_and_crash_recovery_replays_pending_events() -> None:
    settings = _settings()
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    first = MemoryHookManager(settings=settings, logger=get_logger("test"))
    await first.emit(MemoryEventType.ON_USER_MESSAGE, "s1", {"content": "persisted"})

    second = MemoryHookManager(settings=settings, logger=get_logger("test"))
    seen: list[str] = []

    async def handler(event: MemoryEvent) -> None:
        seen.append(event.payload["content"])

    await second.register_handler(MemoryEventType.ON_USER_MESSAGE, handler)
    await second.start()
    await asyncio.sleep(0.05)
    await second.stop()

    assert seen == ["persisted"]
    assert not list(settings.event_queue_dir.glob("*.json"))


@pytest.mark.asyncio
async def test_health_metrics_track_throughput_retries_failures_and_latency() -> None:
    settings = _settings().model_copy(update={"retry_attempts": 1})
    settings.ensure_directories()
    configure_logging(settings.logs_dir, settings.log_level)
    manager = MemoryHookManager(settings=settings, logger=get_logger("test"))

    async def ok(event: MemoryEvent) -> None:
        return None

    async def broken(event: MemoryEvent) -> None:
        raise RuntimeError("fail")

    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, ok)
    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, broken)
    await manager.start()
    await manager.emit(MemoryEventType.ON_USER_MESSAGE, "s1", {"content": "hello"})
    await asyncio.sleep(0.05)
    await manager.stop()

    metrics = manager.health_metrics()
    assert metrics["event_throughput"] >= 1
    assert metrics["failure_rate"] >= 1
    assert metrics["worker_latency_ms"] >= 0
    assert metrics["queue_pressure"] == 0


def test_hermes_compatibility_adapter_normalizes_hook_payloads() -> None:
    adapter = HermesCompatibilityAdapter()

    event = adapter.to_event(MemoryEventType.ON_ASSISTANT_RESPONSE, session_id="s1", content="answer", trace_id="t1")

    assert event.event_type == MemoryEventType.ON_ASSISTANT_RESPONSE
    assert event.trace_id == "t1"
    assert event.payload["content"] == "answer"
