from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_storage_repository_roundtrip(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "managerless.db")
    await repo.open()

    memory_id = await repo.store_memory(
        MemoryRecord(
            memory_id="roundtrip-1",
            memory_type="FACT",
            content="Hermes remembers the blue notebook.",
            importance_score=0.8,
            confidence_score=0.9,
        )
    )

    record = await repo.get_memory(memory_id)
    assert record is not None
    assert record["content"] == "Hermes remembers the blue notebook."

    results = await repo.search_full_text("blue")
    assert len(results) == 1
    assert results[0]["memory_id"] == memory_id

    await repo.close()


@pytest.mark.asyncio
async def test_storage_conflicts_and_quarantine(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "conflict.db")
    await repo.open()

    await repo.store_memory(MemoryRecord(memory_id="source", memory_type="FACT", content="Paris is the capital of France."))
    await repo.store_memory(MemoryRecord(memory_id="conflict", memory_type="FACT", content="Lyon is the capital of France."))
    await repo.add_conflict("source", "conflict", "conflicting capital claim")
    await repo.supersede_memory("source", "conflict")
    await repo.quarantine_memory("conflict", "policy review")

    superseded = await repo.get_memory("source")
    assert superseded is not None
    assert superseded["active_state"] == "superseded"
    assert superseded["superseded_by"] == "conflict"

    await repo.close()
