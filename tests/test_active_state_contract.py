"""P1: Active state contract tests — verify lifecycle semantics."""
from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_archive_cold_memories_sets_archived(tmp_path: Path) -> None:
    """archive_cold_memories() must set active_state='archived'."""
    from memoryx.consolidation.engine import ConsolidationEngine
    repo = MemoryRepository(tmp_path / "state-archive.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="cold-1", memory_type="FACT", content="Cold", importance_score=0.1, decay_score=0.95, access_count=0))
    engine = ConsolidationEngine(repository=repo)
    count = await engine.archive_cold_memories()
    assert count >= 1
    record = await repo.get_memory("cold-1")
    assert record["active_state"] == "archived"
    await repo.close()


@pytest.mark.asyncio
async def test_merge_duplicates_sets_superseded(tmp_path: Path) -> None:
    """merge_duplicates() must set active_state='superseded' on older duplicate."""
    from memoryx.consolidation.engine import ConsolidationEngine
    repo = MemoryRepository(tmp_path / "state-supersede.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="dup-1", memory_type="PROJECT", content="Same", importance_score=0.8))
    await repo.store_memory(MemoryRecord(memory_id="dup-2", memory_type="PROJECT", content="Same", importance_score=0.7))
    engine = ConsolidationEngine(repository=repo)
    count = await engine.merge_duplicates()
    assert count >= 1
    older = await repo.get_memory("dup-2")
    assert older["active_state"] == "superseded"
    await repo.close()


@pytest.mark.asyncio
async def test_quarantine_sets_quarantined(tmp_path: Path) -> None:
    """quarantine_memory() must set active_state='quarantined'."""
    repo = MemoryRepository(tmp_path / "state-quarantine.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="q1", memory_type="FACT", content="Sensitive"))
    await repo.quarantine_memory("q1", "policy review")
    record = await repo.get_memory("q1")
    assert record["active_state"] == "quarantined"
    await repo.close()


@pytest.mark.asyncio
async def test_supersede_sets_superseded(tmp_path: Path) -> None:
    """supersede_memory() must set active_state='superseded'."""
    repo = MemoryRepository(tmp_path / "state-supersede2.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="old", memory_type="FACT", content="Old fact"))
    await repo.store_memory(MemoryRecord(memory_id="new", memory_type="FACT", content="New fact"))
    await repo.supersede_memory("old", "new")
    record = await repo.get_memory("old")
    assert record["active_state"] == "superseded"
    assert record["superseded_by"] == "new"
    await repo.close()


@pytest.mark.asyncio
async def test_list_active_excludes_non_active(tmp_path: Path) -> None:
    """list_active_memories() must only return active_state='active'."""
    repo = MemoryRepository(tmp_path / "state-active-only.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="a1", memory_type="FACT", content="Active"))
    await repo.store_memory(MemoryRecord(memory_id="a2", memory_type="FACT", content="To archive", decay_score=0.95, access_count=0))
    from memoryx.consolidation.engine import ConsolidationEngine
    engine = ConsolidationEngine(repository=repo)
    await engine.archive_cold_memories()
    active = await repo.list_active_memories()
    active_ids = [m["memory_id"] for m in active]
    assert "a1" in active_ids
    assert "a2" not in active_ids
    await repo.close()


@pytest.mark.asyncio
async def test_hierarchy_archive_migration(tmp_path: Path) -> None:
    """HierarchicalMemoryManager.migrate_tiers() must archive cold memories."""
    from memoryx.hierarchy.engine import HierarchicalMemoryManager, MemoryTier
    from memoryx.working_memory import WorkingMemoryEngine
    repo = MemoryRepository(tmp_path / "state-hierarchy.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="cold", memory_type="FACT", content="archive me", importance_score=0.1, decay_score=0.95, access_count=0))
    manager = HierarchicalMemoryManager(repository=repo, working_memory=WorkingMemoryEngine())
    report = await manager.migrate_tiers()
    assert report.migrated_counts.get(MemoryTier.ARCHIVE, 0) == 1
    record = await repo.get_memory("cold")
    assert record["active_state"] != "active"
    archived = await repo.db.fetchall("SELECT memory_id FROM archived_memories WHERE memory_id = ?;", ("cold",))
    assert archived
    await repo.close()
