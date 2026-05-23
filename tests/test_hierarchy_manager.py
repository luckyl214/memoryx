from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.hierarchy import HierarchicalMemoryManager, MemoryTier
from memoryx.storage import MemoryRecord, MemoryRepository
from memoryx.working_memory import WorkingMemoryEngine


@pytest.mark.asyncio
async def test_hierarchical_manager_classifies_hot_semantic_and_archive_tiers(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "hierarchical-classify.db")
    await repo.open()
    await repo.store_memories(
        [
            MemoryRecord(memory_id="hot", memory_type="PROJECT", content="hot project state", importance_score=0.95, access_count=6, scope="project"),
            MemoryRecord(memory_id="semantic", memory_type="FACT", content="stable semantic fact", importance_score=0.7, access_count=1),
            MemoryRecord(memory_id="cold", memory_type="OBSERVATION", content="old cold note", importance_score=0.2, decay_score=0.96, access_count=0),
        ]
    )

    manager = HierarchicalMemoryManager(repository=repo, working_memory=WorkingMemoryEngine())
    tiers = await manager.classify_long_term_tiers()

    assert tiers["hot"] == MemoryTier.LONG_TERM_SEMANTIC
    assert tiers["semantic"] == MemoryTier.CONSOLIDATED_KNOWLEDGE
    assert tiers["cold"] == MemoryTier.ARCHIVE
    await repo.close()


@pytest.mark.asyncio
async def test_hierarchical_manager_migrates_cold_memories_to_archive(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "hierarchical-migrate.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="cold", memory_type="FACT", content="archive me", importance_score=0.1, decay_score=0.95, access_count=0))

    manager = HierarchicalMemoryManager(repository=repo, working_memory=WorkingMemoryEngine())
    report = await manager.migrate_tiers()
    record = await repo.get_memory("cold")
    archived = await repo.db.fetchall("SELECT memory_id, content FROM archived_memories WHERE memory_id = ?;", ("cold",))

    assert report.migrated_counts[MemoryTier.ARCHIVE] == 1
    assert record is not None
    assert int(record["active_state"]) == 0
    assert archived
    await repo.close()


@pytest.mark.asyncio
async def test_hierarchical_manager_reads_working_and_episodic_tiers(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "hierarchical-runtime.db")
    await repo.open()
    working = WorkingMemoryEngine()
    await working.update_task_state(session_id="s1", task="ship phase 33", reasoning_chain=["inspect", "red", "green"])
    episodic_id = await repo.add_episodic_memory(session_id="s1", title="phase 33 event", content="implemented hierarchical memory", importance_score=0.9)

    manager = HierarchicalMemoryManager(repository=repo, working_memory=working)
    working_items = await manager.retrieve_tier(MemoryTier.WORKING, session_id="s1")
    episodic_items = await manager.retrieve_tier(MemoryTier.SHORT_TERM_EPISODIC, session_id="s1")

    assert working_items[0]["current_task"] == "ship phase 33"
    assert episodic_items[0]["episodic_id"] == episodic_id
    await repo.close()


@pytest.mark.asyncio
async def test_hierarchical_manager_performs_tier_aware_retrieval(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "hierarchical-retrieve.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="async memory migration plan", importance_score=0.9, access_count=3, scope="project"))
    await repo.add_episodic_memory(session_id="s1", title="migration incident", content="debugged memory migration", importance_score=0.8)

    manager = HierarchicalMemoryManager(repository=repo, working_memory=WorkingMemoryEngine())
    results = await manager.retrieve(query="memory migration", tiers=[MemoryTier.LONG_TERM_SEMANTIC, MemoryTier.SHORT_TERM_EPISODIC], limit=5)

    assert any(item["tier"] == MemoryTier.LONG_TERM_SEMANTIC for item in results)
    assert any(item["tier"] == MemoryTier.SHORT_TERM_EPISODIC for item in results)
    await repo.close()
