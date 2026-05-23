from __future__ import annotations

import asyncio

import pytest

from memoryx.working_memory import WorkingMemoryEngine


@pytest.mark.asyncio
async def test_working_memory_tracks_taYOUR_API_KEY_HERE() -> None:
    engine = WorkingMemoryEngine(default_ttl_seconds=60)

    await engine.update_task_state(
        session_id="s1",
        task="Implement Phase 24",
        reasoning_chain=["inspect baseline", "write tests"],
        todos=["tests", "implementation"],
    )

    state = await engine.get_state("s1")

    assert state is not None
    assert state.current_task == "Implement Phase 24"
    assert state.reasoning_chain == ["inspect baseline", "write tests"]
    assert state.active_todos == ["tests", "implementation"]


@pytest.mark.asyncio
async def test_working_memory_tracks_debug_and_temporary_context() -> None:
    engine = WorkingMemoryEngine(default_ttl_seconds=60)

    await engine.update_debug_state(
        session_id="s2",
        debug_session={"error": "timeout", "file": "worker.py"},
        temporary_context={"focus": "queue drain"},
    )

    state = await engine.get_state("s2")

    assert state is not None
    assert state.debug_session["error"] == "timeout"
    assert state.temporary_context["focus"] == "queue drain"


@pytest.mark.asyncio
async def test_working_memory_expires_entries() -> None:
    engine = WorkingMemoryEngine(default_ttl_seconds=0.05)

    await engine.update_task_state(session_id="s3", task="short task")
    assert await engine.get_state("s3") is not None

    await asyncio.sleep(0.08)
    await engine.expire_stale()

    assert await engine.get_state("s3") is None


@pytest.mark.asyncio
async def test_working_memory_compresses_short_term_state() -> None:
    engine = WorkingMemoryEngine(default_ttl_seconds=60)

    await engine.update_task_state(
        session_id="s4",
        task="Long workflow",
        reasoning_chain=["step1", "step2", "step3", "step4"],
        todos=["a", "b", "c", "d"],
    )

    summary = await engine.compress_state("s4", max_reasoning_items=2, max_todos=2)
    state = await engine.get_state("s4")

    assert "step1" in summary
    assert state is not None
    assert state.reasoning_chain == ["step1", "step2"]
    assert state.active_todos == ["a", "b"]
