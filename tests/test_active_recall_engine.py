from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.recall import ActiveRecallEngine
from memoryx.storage import MemoryRecord, MemoryRepository


class DummyVectorStore:
    async def search(self, query_vector: list[float], limit: int = 10) -> list[dict]:
        return [
            {"memory_id": "p1", "score": 0.91},
            {"memory_id": "e1", "score": 0.62},
        ]


@pytest.mark.asyncio
async def test_active_recall_returns_preference_context(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "recall-pref.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.9, scope="user"))

    engine = ActiveRecallEngine(repository=repo, vector_store=DummyVectorStore())
    result = await engine.recall(query="remember my preference for Python style", query_vector=[0.1, 0.2], limit=3)

    assert result["route"] == "user"
    assert any(item["memory_id"] == "p1" for item in result["memories"])
    await repo.close()


@pytest.mark.asyncio
async def test_active_recall_supports_debugging_recall(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "recall-debug.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="e1", memory_type="EPISODIC", content="Debugging timeout incident in async queue worker", importance_score=0.88, scope="project", tags_json=json.dumps(["debugging"])))

    engine = ActiveRecallEngine(repository=repo, vector_store=DummyVectorStore())
    result = await engine.recall(query="debug timeout in worker", query_vector=[0.3, 0.4], limit=3)

    assert result["intent"] == "debugging"
    assert any(item["memory_id"] == "e1" for item in result["memories"])
    await repo.close()


@pytest.mark.asyncio
async def test_active_recall_records_access(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "recall-access.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.9, scope="user"))

    engine = ActiveRecallEngine(repository=repo, vector_store=DummyVectorStore())
    await engine.recall(query="remember my preference", query_vector=[0.1, 0.2], limit=3)

    row = await repo.get_memory("p1")
    assert row is not None
    assert int(row["access_count"]) >= 1
    await repo.close()


@pytest.mark.asyncio
async def test_active_recall_project_context_view(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "recall-project.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="pr1", memory_type="PROJECT", content="Project uses SQLite and LanceDB", importance_score=0.85, scope="project"))

    engine = ActiveRecallEngine(repository=repo, vector_store=DummyVectorStore())
    context = await engine.project_recall(query="project architecture stack", query_vector=[0.5, 0.6], limit=3)

    assert context["route"] == "project"
    assert any(item["memory_id"] == "pr1" for item in context["memories"])
    await repo.close()
