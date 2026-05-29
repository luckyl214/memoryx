"""P1: Exposed SQL contract tests — verify column names match schema."""
from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_episodic_session_timeline_has_episodic_id(tmp_path: Path) -> None:
    """session_timeline() must return episodic_id (alias for id)."""
    from memoryx.episodic.engine import EpisodicMemoryEngine
    repo = MemoryRepository(tmp_path / "sql-episodic-timeline.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)
    await engine.record_episode("s1", "test event", ["step1", "step2"], importance_score=0.8)
    rows = await engine.session_timeline("s1")
    assert rows, "no episodes returned"
    assert "episodic_id" in rows[0], f"episodic_id missing from result keys: {list(rows[0].keys())}"
    assert rows[0]["episodic_id"], "episodic_id must not be empty"
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_top_episodes_has_episodic_id(tmp_path: Path) -> None:
    """top_episodes() must return episodic_id."""
    from memoryx.episodic.engine import EpisodicMemoryEngine
    repo = MemoryRepository(tmp_path / "sql-episodic-top.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)
    await engine.record_episode("s1", "top event", ["action"], importance_score=0.9)
    rows = await engine.top_episodes(limit=1)
    assert rows
    assert "episodic_id" in rows[0]
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_search_has_episodic_id(tmp_path: Path) -> None:
    """search() must return episodic_id."""
    from memoryx.episodic.engine import EpisodicMemoryEngine
    repo = MemoryRepository(tmp_path / "sql-episodic-search.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)
    await engine.record_episode("s1", "deploy incident", ["rollback"], importance_score=0.7)
    rows = await engine.search("rollback")
    assert rows
    assert "episodic_id" in rows[0]
    await repo.close()


@pytest.mark.asyncio
async def test_relations_uses_id_column(tmp_path: Path) -> None:
    """Relations table uses 'id' as PK, not 'relation_id'."""
    repo = MemoryRepository(tmp_path / "sql-relations.db")
    await repo.open()
    source_id = await repo.add_entity("src", "project")
    target_id = await repo.add_entity("tgt", "project")
    rel_id = await repo.add_relation(source_id, target_id, "related_to", 0.5)
    # Must query with 'id', not 'relation_id'
    row = await repo.db.fetchone("SELECT id FROM relations WHERE id = ?;", (rel_id,))
    assert row is not None, "relation not found by id"
    assert row["id"] == rel_id
    await repo.close()


@pytest.mark.asyncio
async def test_audit_logs_uses_metadata_json(tmp_path: Path) -> None:
    """audit_logs uses 'metadata_json', not 'payload_json'."""
    repo = MemoryRepository(tmp_path / "sql-audit.db")
    await repo.open()
    await repo.append_audit("test_type", "e1", "test_action", before_json={"key": "value"})
    # Must query with 'metadata_json', not 'payload_json'
    rows = await repo.db.fetchall("SELECT action, metadata_json FROM audit_logs WHERE action = ?;", ("test_action",))
    assert rows
    assert rows[0]["metadata_json"] is not None
    await repo.close()


@pytest.mark.asyncio
async def test_hierarchical_episodic_tier_has_episodic_id(tmp_path: Path) -> None:
    """HierarchicalMemoryManager episodic tier must return episodic_id."""
    from memoryx.episodic.engine import EpisodicMemoryEngine
    from memoryx.hierarchy.engine import HierarchicalMemoryManager, MemoryTier
    from memoryx.working_memory import WorkingMemoryEngine
    repo = MemoryRepository(tmp_path / "sql-hierarchy.db")
    await repo.open()
    await repo.add_episodic_memory(session_id="s1", content="test episodic", importance_score=0.8)
    manager = HierarchicalMemoryManager(repository=repo, working_memory=WorkingMemoryEngine())
    rows = await manager.retrieve_tier(MemoryTier.SHORT_TERM_EPISODIC, session_id="s1")
    assert rows
    assert "episodic_id" in rows[0], f"episodic_id missing: {list(rows[0].keys())}"
    await repo.close()
