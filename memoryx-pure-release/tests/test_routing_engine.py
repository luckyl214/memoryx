from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings import VectorStore
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.routing import MemoryRouter, RoutingIntent
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_router_detects_debugging_intent(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "route.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="d1", memory_type="EPISODIC", content="Fixed timeout bug in queue worker", importance_score=0.9, scope="project"))
    store = VectorStore(tmp_path / "route-vectors.json")
    await store.open()
    await store.upsert("d1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "d1"})
    retrieval = HybridRetrievalEngine(repository=repo, vector_store=store)
    router = MemoryRouter(retrieval_engine=retrieval)

    plan = await router.route(query="why is my queue timeout failing?", query_vector=[1.0, 0.0, 0.0, 0.0])

    assert plan.intent == RoutingIntent.DEBUGGING
    assert plan.primary_route == "debugging"
    assert plan.results[0].memory_id == "d1"
    await repo.close()


@pytest.mark.asyncio
async def test_router_prefers_project_route_for_planning(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "route-project.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="p1", memory_type="PROJECT", content="Project milestone and architecture decisions", importance_score=0.95, scope="project"))
    store = VectorStore(tmp_path / "route-project-vectors.json")
    await store.open()
    await store.upsert("p1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "p1"})
    retrieval = HybridRetrievalEngine(repository=repo, vector_store=store)
    router = MemoryRouter(retrieval_engine=retrieval)

    plan = await router.route(query="help me plan the next project milestone", query_vector=[1.0, 0.0, 0.0, 0.0])

    assert plan.intent == RoutingIntent.PLANNING
    assert plan.primary_route == "planning"
    await repo.close()


@pytest.mark.asyncio
async def test_router_fuses_multiple_routes(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "route-fuse.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="u1", memory_type="PREFERENCE", content="User prefers concise responses", importance_score=0.8, scope="user"))
    await repo.store_memory(MemoryRecord(memory_id="e1", memory_type="EPISODIC", content="Discussed deployment incident and rollback", importance_score=0.9, scope="project"))
    store = VectorStore(tmp_path / "route-fuse-vectors.json")
    await store.open()
    await store.upsert("u1", [0.5, 0.5, 0.0, 0.0], {"memory_id": "u1"})
    await store.upsert("e1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "e1"})
    retrieval = HybridRetrievalEngine(repository=repo, vector_store=store)
    router = MemoryRouter(retrieval_engine=retrieval)

    plan = await router.route(query="remember my preference and deployment incident", query_vector=[1.0, 0.0, 0.0, 0.0])

    assert len(plan.results) >= 1
    assert plan.route_scores["project"] >= 0.0
    assert plan.route_scores["user"] >= 0.0
    await repo.close()
