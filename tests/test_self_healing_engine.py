from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.self_healing import SelfHealingEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_self_healing_detects_and_repairs_checksum_drift(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "self-healing-checksum.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="stable fact"))
    await repo.db.execute("UPDATE memories SET checksum = ? WHERE memory_id = ?;", ("bad-checksum", "m1"))

    engine = SelfHealingEngine(repository=repo)
    report = await engine.run_once(repair=True)
    repaired = await repo.get_memory("m1")

    assert "checksum_drift" in report.detected_issues
    assert report.repaired_counts["checksum_drift"] == 1
    assert repaired is not None
    assert repaired["checksum"] == repo.checksum("stable fact")
    await repo.close()


@pytest.mark.asyncio
async def test_self_healing_removes_orphan_relations(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "self-healing-orphans.db")
    await repo.open()
    source_id = await repo.add_entity("source", "project")
    target_id = await repo.add_entity("target", "project")
    relation_id = await repo.add_relation(source_id, target_id, "related_to", 0.5)
    await repo.db.execute("PRAGMA foreign_keys = OFF;")
    await repo.db.execute("DELETE FROM entities WHERE entity_id = ?;", (target_id,))
    await repo.db.execute("PRAGMA foreign_keys = ON;")

    engine = SelfHealingEngine(repository=repo)
    report = await engine.run_once(repair=True)
    orphan = await repo.db.fetchone("SELECT relation_id FROM relations WHERE relation_id = ?;", (relation_id,))

    assert "orphan_relations" in report.detected_issues
    assert report.repaired_counts["orphan_relations"] == 1
    assert orphan is None
    await repo.close()


@pytest.mark.asyncio
async def test_self_healing_marks_stale_embeddings_for_refresh(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "self-healing-embeddings.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="PROJECT", content="needs fresh vector"))
    await repo.db.execute(
        "INSERT INTO memory_embeddings(embedding_id, memory_id, vector, dimension, freshness_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now', '-40 days'), datetime('now', '-40 days'));",
        ("e2", "m2", b"vector", 2, 0.1),
    )

    engine = SelfHealingEngine(repository=repo, stale_embedding_days=30)
    report = await engine.run_once(repair=True)
    rows = await repo.db.fetchall("SELECT action, payload_json FROM audit_logs WHERE action = ?;", ("embedding_refresh_needed",))

    assert "stale_embeddings" in report.detected_issues
    assert report.repaired_counts["stale_embeddings"] == 1
    assert len(rows) == 1
    assert "m2" in rows[0]["payload_json"]
    await repo.close()


@pytest.mark.asyncio
async def test_self_healing_reports_corruption_check_without_repairing(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "self-healing-integrity.db")
    await repo.open()

    engine = SelfHealingEngine(repository=repo)
    report = await engine.run_once(repair=False)

    assert report.integrity_status == "ok"
    assert report.repair_enabled is False
    assert report.detected_issues == []
    await repo.close()
