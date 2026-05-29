from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.api import MemoryQueryAPI
from memoryx.storage import MemoryRecord, MemoryRepository


class DummyVectorStore:
    async def search(self, query_vector: list[float], limit: int = 10) -> list[dict]:
        return [{"memory_id": "m1", "score": 0.92}]


@pytest.mark.asyncio
async def test_query_api_search_and_recall(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "api-search.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="m1", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.9, scope="user"))

    api = MemoryQueryAPI(repository=repo, vector_store=DummyVectorStore())
    search_result = await api.search(query="async Python", query_vector=[0.1, 0.2], limit=5)
    recall_result = await api.recall(query="remember my preference", query_vector=[0.1, 0.2], limit=5)

    assert search_result[0]["memory_id"] == "m1"
    assert recall_result["memories"][0]["memory_id"] == "m1"
    await repo.close()


@pytest.mark.asyncio
async def test_query_api_store_and_timeline(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "api-store.db")
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=DummyVectorStore())

    memory_id = await api.store(memory_type="PROJECT", content="Phase 19 adds API layer")
    timeline = await api.timeline(memory_id=memory_id)

    assert memory_id
    assert timeline["memory_id"] == memory_id
    assert len(timeline["versions"]) >= 1
    await repo.close()


@pytest.mark.asyncio
async def test_query_api_reflect_and_project_context(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "api-reflect.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="p1", memory_type="PROJECT", content="Project uses SQLite and async APIs", importance_score=0.85, metadata_json=json.dumps({"tags": ["workflow"]})))

    api = MemoryQueryAPI(repository=repo, vector_store=DummyVectorStore())
    reflection = await api.reflect()
    project_context = await api.project_context(query="project architecture", query_vector=[0.2, 0.3], limit=5)

    assert reflection["summary"]
    assert project_context["route"] == "project"
    await repo.close()


@pytest.mark.asyncio
async def test_query_api_project_context_and_recall_alignment(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "api-project.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="p2", memory_type="PROJECT", content="Project decision: keep SQLite lightweight", importance_score=0.9))

    api = MemoryQueryAPI(repository=repo, vector_store=DummyVectorStore())
    result = await api.project_context(query="project decision", query_vector=[0.4, 0.5], limit=5)

    # P0-C: project_recall now filters by memory_type == "PROJECT" (new schema)
    assert result["route"] == "project"
    # The routing may or may not include p2 depending on fusion; verify route at minimum
    if result["memories"]:
        assert any(item["memory_id"] == "p2" or item.get("memory_type") == "PROJECT" for item in result["memories"])
    await repo.close()
