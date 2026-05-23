from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository
from memoryx.retrieval import HybridRetrievalEngine


class DummyVectorStore:
    def __init__(self):
        self.data: dict[str, dict] = {}
    async def open(self):
        pass
    async def search(self, query_vector: list[float], limit: int = 10) -> list[dict]:
        results = [
            {"memory_id": mid, "score": item.get("score", 0.5)}
            for mid, item in self.data.items()
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    async def upsert(self, memory_id, vector, metadata):
        self.data[memory_id] = {"score": 0.5, **metadata}


@pytest.mark.asyncio
async def test_tag_filter_filters_by_any_tag(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "tag-any.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="async project",
                                          tags_json='["python", "async"]', importance_score=0.9, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="FACT", content="coffee preference",
                                          tags_json='["preference"]', importance_score=0.7, scope="user"))

    store = DummyVectorStore()
    for mid in ["m1", "m2"]:
        await store.upsert(mid, [1.0, 0.0], {})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="project", query_vector=[1.0, 0.0], tag_filter=["python"], tag_mode="any")

    assert len(results) == 1
    assert results[0].memory_id == "m1"
    await repo.close()


@pytest.mark.asyncio
async def test_tag_filter_requires_all_tags(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "tag-all.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="async project",
                                          tags_json='["python", "async", "workflow"]', importance_score=0.9, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="FACT", content="sync code",
                                          tags_json='["python"]', importance_score=0.5, scope="user"))

    store = DummyVectorStore()
    for mid in ["m1", "m2"]:
        await store.upsert(mid, [1.0, 0.0], {})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="project", query_vector=[1.0, 0.0],
                                     tag_filter=["python", "async"], tag_mode="all")

    assert len(results) == 1
    assert results[0].memory_id == "m1"
    await repo.close()


@pytest.mark.asyncio
async def test_no_tag_filter_returns_all(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "tag-none.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="PROJECT", content="project a",
                                          tags_json='["python"]', importance_score=0.9, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="FACT", content="fact b",
                                          tags_json='["other"]', importance_score=0.7, scope="user"))

    store = DummyVectorStore()
    for mid in ["m1", "m2"]:
        await store.upsert(mid, [1.0, 0.0], {})

    engine = HybridRetrievalEngine(repository=repo, vector_store=store)
    results = await engine.retrieve(query="project", query_vector=[1.0, 0.0])

    assert len(results) == 2
    await repo.close()
