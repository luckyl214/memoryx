from __future__ import annotations

import time
from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_schema_and_fts_roundtrip(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "memoryx.db")
    await repo.open()

    record = MemoryRecord(
        id="m1",
        memory_type="FACT",
        content="Example user likes async Python",
    )
    await repo.store_memory(record)

    fetched = await repo.get_memory("m1")
    assert fetched is not None
    assert fetched["content"] == "Example user likes async Python"
    assert fetched["memory_type"] == "FACT"

    results = await repo.search_full_text("async")
    assert results and results[0]["id"] == "m1"

    active = await repo.list_active_memories()
    assert active[0]["id"] == "m1"

    await repo.record_access("m1")
    updated = await repo.get_memory("m1")
    assert updated is not None and updated["access_count"] == 1

    await repo.add_session_summary("s1", "summary text")
    await repo.add_episodic_memory(memory_id="m1", session_id="s1", content="fixed queue bug", summary="debugging episode")
    await repo.add_entity("Hermes")
    await repo.quarantine_memory("m1", "suspicious")
    await repo.rollback_memory("m1")

    export_dir = tmp_path / "exports"
    paths = await repo.export_markdown(export_dir)
    assert paths and paths[0].exists()

    await repo.close()


@pytest.mark.asyncio
async def test_conflict_and_supersede_flow(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "memoryx2.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="a", memory_type="PREFERENCE", content="喜欢轻量级"))
    await repo.store_memory(MemoryRecord(id="b", memory_type="PREFERENCE", content="喜欢重量级"))
    await repo.add_conflict("a", "b", "opposite preference")
    await repo.supersede_memory("a", "b")

    a = await repo.get_memory("a")
    assert a is not None and a["active_state"] == "superseded" and a["superseded_by"] == "b"

    await repo.close()


@pytest.mark.asyncio
async def test_batch_write_smoke(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "memoryx3.db")
    await repo.open()

    started = time.perf_counter()
    for i in range(5):
        await repo.store_memory(MemoryRecord(id=f"m{i}", memory_type="OBSERVATION", content=f"item {i}"))
    elapsed = time.perf_counter() - started

    rows = await repo.list_active_memories(limit=10)
    assert len(rows) == 5
    assert elapsed < 2.0
    await repo.close()
