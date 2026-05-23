from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.graph import EntityGraphEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_graph_engine_links_entities_from_memory(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "graph.db")
    await repo.open()
    await repo.store_memory(
        MemoryRecord(
            memory_id="m1",
            memory_type="PROJECT",
            content="Hermes uses Python and SQLite",
            entities_json=json.dumps(["Hermes", "Python", "SQLite"]),
            scope="project",
        )
    )

    engine = EntityGraphEngine(repository=repo)
    created = await engine.ingest_memory_entities("m1")

    assert created >= 3
    graph = await engine.neighbors("Hermes")
    names = {item["entity_name"] for item in graph}
    assert "Python" in names
    assert "SQLite" in names
    await repo.close()


@pytest.mark.asyncio
async def test_graph_engine_traverses_related_entities(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "graph-traverse.db")
    await repo.open()
    engine = EntityGraphEngine(repository=repo)

    hermes = await engine.ensure_entity("Hermes", entity_type="project")
    python_id = await engine.ensure_entity("Python", entity_type="technology")
    sqlite_id = await engine.ensure_entity("SQLite", entity_type="technology")
    await repo.add_relation(hermes, python_id, "uses", 0.9)
    await repo.add_relation(python_id, sqlite_id, "integrates_with", 0.8)

    path = await engine.traverse("Hermes", depth=2)

    names = {item["entity_name"] for item in path}
    assert names == {"Hermes", "Python", "SQLite"}
    await repo.close()


@pytest.mark.asyncio
async def test_graph_engine_builds_project_graph(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "graph-project.db")
    await repo.open()
    await repo.store_memory(
        MemoryRecord(
            memory_id="m2",
            memory_type="PROJECT",
            content="Mnemosyne-X uses LanceDB and Qwen3 embeddings",
            entities_json=json.dumps(["Mnemosyne-X", "LanceDB", "Qwen3"]),
            scope="project",
        )
    )

    engine = EntityGraphEngine(repository=repo)
    await engine.ingest_memory_entities("m2")
    project_graph = await engine.project_graph()

    names = {item["entity_name"] for item in project_graph}
    assert "Mnemosyne-X" in names
    assert "LanceDB" in names
    assert "Qwen3" in names
    await repo.close()


@pytest.mark.asyncio
async def test_graph_engine_orders_neighbors_by_weight(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "graph-weight.db")
    await repo.open()
    engine = EntityGraphEngine(repository=repo)

    hermes = await engine.ensure_entity("Hermes", entity_type="project")
    python_id = await engine.ensure_entity("Python", entity_type="technology")
    sqlite_id = await engine.ensure_entity("SQLite", entity_type="technology")
    await repo.add_relation(hermes, sqlite_id, "uses", 0.4)
    await repo.add_relation(hermes, python_id, "uses", 0.9)

    neighbors = await engine.neighbors("Hermes")

    assert neighbors[0]["entity_name"] == "Python"
    assert neighbors[1]["entity_name"] == "SQLite"
    await repo.close()
