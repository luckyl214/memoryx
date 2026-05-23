from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.consolidation import ConsolidationEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_consolidation_generates_session_summary(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "consolidation.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="Implemented async queue worker for memory hooks", importance_score=0.8, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="TASK", content="Added retry and timeout handling to API client", importance_score=0.7, scope="project"))

    engine = ConsolidationEngine(repository=repo)
    summary = await engine.summarize_session(session_id="s1")

    assert "Implemented async queue worker" in summary or "retry and timeout" in summary
    await repo.close()


@pytest.mark.asyncio
async def test_consolidation_applies_decay_to_old_low_access_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "decay.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="Old low-value fact", importance_score=0.4, recency_score=0.1, access_count=0))

    engine = ConsolidationEngine(repository=repo)
    updated = await engine.apply_decay()

    record = await repo.get_memory("m1")
    assert updated >= 1
    assert record is not None
    assert float(record["decay_score"]) > 0.0
    await repo.close()


@pytest.mark.asyncio
async def test_consolidation_archives_cold_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "archive.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="cold-1", memory_type="FACT", content="Cold archived memory", importance_score=0.2, decay_score=0.95, access_count=0))

    engine = ConsolidationEngine(repository=repo)
    archived = await engine.archive_cold_memories()

    assert archived >= 1
    record = await repo.get_memory("cold-1")
    assert record is not None
    assert str(record["active_state"]) == "quarantined"
    await repo.close()


@pytest.mark.asyncio
async def test_consolidation_reinforces_high_value_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reinforce.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="hot-1", memory_type="PROJECT", content="Critical project memory", importance_score=0.95, access_count=5, reinforcement_score=0.1, scope="project"))

    engine = ConsolidationEngine(repository=repo)
    reinforced = await engine.reinforce_memories()

    record = await repo.get_memory("hot-1")
    assert reinforced >= 1
    assert record is not None
    assert float(record["reinforcement_score"]) > 0.1
    await repo.close()


@pytest.mark.asyncio
async def test_consolidation_merges_duplicate_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "merge.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="dup-1", memory_type="PROJECT", content="Same project memory", importance_score=0.8, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="dup-2", memory_type="PROJECT", content="Same project memory", importance_score=0.7, scope="project"))

    engine = ConsolidationEngine(repository=repo)
    merged = await engine.merge_duplicates()

    assert merged >= 1
    older = await repo.get_memory("dup-2")
    assert older is not None
    assert str(older["active_state"]) == "quarantined"
    await repo.close()
