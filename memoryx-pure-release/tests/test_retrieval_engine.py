from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings import VectorStore
from memoryx.retrieval import HybridRetrievalEngine, RetrievalIntent
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_hybrid_retrieval_prefers_semantic_and_keyword_overlap(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "retrieval.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="Project uses async Python workers", importance_score=0.9, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="FACT", content="User likes coffee", importance_score=0.4, scope="user"))

    store = VectorStore(tmp_path / "vectors.json")
    await store.open()
    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "m1"})
    await store.upsert("m2", [0.1, 0.9, 0.0, 0.0], {"memory_id": "m2"})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="async python workers", query_vector=[1.0, 0.0, 0.0, 0.0], limit=2)

    assert results[0].memory_id == "m1"
    assert results[0].final_score >= results[1].final_score
    await repo.close()


@pytest.mark.asyncio
async def test_hybrid_retrieval_filters_by_scope(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "scope.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="user-memory", memory_type="PREFERENCE", content="User prefers concise replies", scope="user"))
    await repo.store_memory(MemoryRecord(memory_id="project-memory", memory_type="PROJECT", content="Project uses SQLite storage", scope="project"))

    store = VectorStore(tmp_path / "scope-vectors.json")
    await store.open()
    await store.upsert("user-memory", [1.0, 0.0, 0.0, 0.0], {"memory_id": "user-memory"})
    await store.upsert("project-memory", [1.0, 0.0, 0.0, 0.0], {"memory_id": "project-memory"})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="sqlite storage", query_vector=[1.0, 0.0, 0.0, 0.0], scope_filter="project", limit=5)

    assert [item.memory_id for item in results] == ["project-memory"]
    await repo.close()


@pytest.mark.asyncio
async def test_intent_aware_weights_help_debugging_query(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "intent.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="debug-1", memory_type="EPISODIC", content="Debugged queue timeout and retry issue", importance_score=0.8, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="plan-1", memory_type="TASK", content="Plan marketing content calendar", importance_score=0.8, scope="project"))

    store = VectorStore(tmp_path / "intent-vectors.json")
    await store.open()
    await store.upsert("debug-1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "debug-1"})
    await store.upsert("plan-1", [0.6, 0.4, 0.0, 0.0], {"memory_id": "plan-1"})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(
        query="debug queue timeout issue",
        query_vector=[1.0, 0.0, 0.0, 0.0],
        intent=RetrievalIntent.DEBUGGING,
        limit=2,
    )

    assert results[0].memory_id == "debug-1"
    assert results[0].explanation
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_retrieval_boosts_episode_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "episodic.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="e1", memory_type="EPISODIC", content="Deployment incident timeline and rollback", importance_score=0.7, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="f1", memory_type="FACT", content="Deployment checklist exists", importance_score=0.7, scope="project"))

    store = VectorStore(tmp_path / "episodic-vectors.json")
    await store.open()
    await store.upsert("e1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "e1"})
    await store.upsert("f1", [0.9, 0.1, 0.0, 0.0], {"memory_id": "f1"})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="deployment incident rollback", query_vector=[1.0, 0.0, 0.0, 0.0], limit=2)

    assert results[0].memory_id == "e1"
    await repo.close()
