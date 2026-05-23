from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.compression import SemanticCompressionEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_compression_clusters_similar_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "compression-cluster.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="c1", memory_type="PREFERENCE", content="User prefers async Python architecture", importance_score=0.9))
    await repo.store_memory(MemoryRecord(id="c2", memory_type="PREFERENCE", content="User prefers async Python coding patterns", importance_score=0.8))

    engine = SemanticCompressionEngine(repository=repo)
    clusters = await engine.cluster_memories()

    assert len(clusters) == 1
    assert {"c1", "c2"} == set(clusters[0]["memory_ids"])
    await repo.close()


@pytest.mark.asyncio
async def test_compression_builds_cluster_summary(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "compression-summary.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="c3", memory_type="PROJECT", content="Project uses SQLite WAL mode for reliability", importance_score=0.85))
    await repo.store_memory(MemoryRecord(id="c4", memory_type="PROJECT", content="Project uses SQLite WAL mode for low-memory stability", importance_score=0.82))

    engine = SemanticCompressionEngine(repository=repo)
    clusters = await engine.cluster_memories()
    summary = engine.summarize_cluster(clusters[0]["memories"])

    assert "Project uses SQLite WAL mode" in summary
    await repo.close()


@pytest.mark.asyncio
async def test_compression_merges_duplicate_chunks(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "compression-merge.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="c5", memory_type="FACT", content="Hermes should stay non-invasive", importance_score=0.9))
    await repo.store_memory(MemoryRecord(id="c6", memory_type="FACT", content="Hermes should stay non-invasive", importance_score=0.7))

    engine = SemanticCompressionEngine(repository=repo)
    merged = await engine.merge_duplicate_chunks()

    duplicate = await repo.get_memory("c6")
    assert merged == 1
    assert duplicate is not None
    assert duplicate["active_state"] == "superseded"
    await repo.close()


@pytest.mark.asyncio
async def test_compression_creates_hierarchical_summary_and_archives(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "compression-hierarchy.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="c7", memory_type="PROJECT", content="Phase 1 hook layer added async queue", importance_score=0.8, decay_score=0.95, access_count=0))
    await repo.store_memory(MemoryRecord(id="c8", memory_type="PROJECT", content="Phase 1 hook layer added graceful shutdown", importance_score=0.81, decay_score=0.95, access_count=0))

    engine = SemanticCompressionEngine(repository=repo)
    result = await engine.compress_to_hierarchical_summary(session_id="phase-1")

    summaries = await repo.db.fetchall("SELECT session_id, summary FROM session_summaries WHERE session_id = ?;", ("phase-1",))
    archives = await repo.db.fetchall("SELECT memory_id FROM archived_memories ORDER BY memory_id;", ())
    assert result["clusters"] >= 1
    assert len(summaries) == 1
    assert len(archives) >= 1
    await repo.close()
