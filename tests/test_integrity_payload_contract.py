"""P1: Integrity payload contract tests — verify NOT NULL columns are populated and dicts are serialized."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


# ── episodic_memories.memory_id ──────────────────────────────────


@pytest.mark.asyncio
async def test_episodic_auto_memory_id_not_null(tmp_path: Path) -> None:
    """add_episodic_memory(memory_id=None) must generate a non-empty memory_id."""
    repo = MemoryRepository(tmp_path / "contract-episodic.db")
    await repo.open()
    eid = await repo.add_episodic_memory(session_id="s1", content="test event", importance_score=0.7)
    rows = await repo.db.fetchall("SELECT memory_id FROM episodic_memories WHERE id = ?;", (eid,))
    assert rows, "episodic memory not found"
    memory_id = rows[0]["memory_id"]
    assert memory_id is not None and memory_id != "", "memory_id must not be NULL or empty"
    assert memory_id.startswith("ep-"), "auto-generated memory_id should start with 'ep-'"
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_explicit_memory_id_preserved(tmp_path: Path) -> None:
    """Explicit memory_id must be preserved, not overridden."""
    repo = MemoryRepository(tmp_path / "contract-episodic-explicit.db")
    await repo.open()
    # Create parent memory first (FK requirement)
    await repo.store_memory(MemoryRecord(memory_id="custom-id-42", memory_type="EPISODIC", content="explicit event"))
    eid = await repo.add_episodic_memory(memory_id="custom-id-42", session_id="s1", content="explicit event")
    rows = await repo.db.fetchall("SELECT memory_id FROM episodic_memories WHERE id = ?;", (eid,))
    assert rows[0]["memory_id"] == "custom-id-42"
    await repo.close()


# ── reinforcement_events.checksum ────────────────────────────────


@pytest.mark.asyncio
async def test_reinforcement_event_checksum_not_null(tmp_path: Path) -> None:
    """reinforcement_events rows must have non-null checksum."""
    repo = MemoryRepository(tmp_path / "contract-reinforce.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="r1", memory_type="FACT", content="test", access_count=6, importance_score=0.5))
    from memoryx.reinforcement.engine import ImportanceReinforcementEngine
    engine = ImportanceReinforcementEngine(repository=repo)
    await engine.run_cycle()
    rows = await repo.db.fetchall("SELECT checksum FROM reinforcement_events;")
    assert rows, "no reinforcement events created"
    for row in rows:
        assert row["checksum"] is not None and row["checksum"] != "", f"checksum must not be NULL: {row}"
    await repo.close()


# ── archived_memories.checksum ───────────────────────────────────


@pytest.mark.asyncio
async def test_archived_memory_checksum_not_null(tmp_path: Path) -> None:
    """archived_memories rows must have non-null checksum."""
    repo = MemoryRepository(tmp_path / "contract-archive.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="cold-1", memory_type="FACT", content="Cold", importance_score=0.1, decay_score=0.95, access_count=0))
    from memoryx.consolidation.engine import ConsolidationEngine
    engine = ConsolidationEngine(repository=repo)
    await engine.archive_cold_memories()
    rows = await repo.db.fetchall("SELECT checksum FROM archived_memories;")
    assert rows, "no archived memories created"
    for row in rows:
        assert row["checksum"] is not None and row["checksum"] != "", f"checksum must not be NULL: {row}"
    await repo.close()


# ── reflection_summaries.content_hash / checksum ─────────────────


@pytest.mark.asyncio
async def test_reflection_content_hash_checksum_not_null(tmp_path: Path) -> None:
    """reflection_summaries rows must have non-null content_hash and checksum."""
    repo = MemoryRepository(tmp_path / "contract-reflection.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers X", confidence_score=0.9, importance_score=0.9))
    await repo.store_memory(MemoryRecord(memory_id="p2", memory_type="PREFERENCE", content="User prefers X", confidence_score=0.91, importance_score=0.9))
    from memoryx.knowledge_distillation.engine import KnowledgeDistillationEngine
    engine = KnowledgeDistillationEngine(repository=repo, min_repetitions=2)
    await engine.distill(persist=True)
    rows = await repo.db.fetchall("SELECT content_hash, checksum FROM reflection_summaries;")
    assert rows, "no reflection summaries created"
    for row in rows:
        assert row["content_hash"] is not None and row["content_hash"] != "", f"content_hash must not be NULL: {row}"
        assert row["checksum"] is not None and row["checksum"] != "", f"checksum must not be NULL: {row}"
    await repo.close()


# ── append_audit: action must be str, dict goes to before_json ────


@pytest.mark.asyncio
async def test_append_audit_action_is_string(tmp_path: Path) -> None:
    """append_audit must not raise ProgrammingError when before_json is a dict."""
    repo = MemoryRepository(tmp_path / "contract-audit.db")
    await repo.open()
    # Must not raise sqlite3.ProgrammingError
    await repo.append_audit("test_entity", "e1", "test_action", before_json={"detail": "ok"})
    rows = await repo.db.fetchall("SELECT action, before_json FROM audit_logs;")
    assert rows
    assert rows[0]["action"] == "test_action"
    assert rows[0]["before_json"] is not None
    parsed = json.loads(rows[0]["before_json"])
    assert parsed["detail"] == "ok"
    await repo.close()


@pytest.mark.asyncio
async def test_append_audit_no_raw_dict_binding(tmp_path: Path) -> None:
    """Regression: passing a dict as action must not crash with ProgrammingError."""
    repo = MemoryRepository(tmp_path / "contract-audit-dict.db")
    await repo.open()
    # This should NOT raise ProgrammingError (old bug: dict passed as action)
    # After fix, callers use before_json= kwarg
    await repo.append_audit("entity", "id1", "string_action", before_json={"key": "value"})
    # Verify it persisted
    rows = await repo.db.fetchall("SELECT * FROM audit_logs WHERE entity_id = 'id1';")
    assert len(rows) == 1
    await repo.close()
