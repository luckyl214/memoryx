"""P1: LanceDB vector store smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings import LanceDBVectorStore


@pytest.mark.asyncio
async def test_lancedb_upsert_and_search(tmp_path: Path) -> None:
    store = LanceDBVectorStore(tmp_path / "lancedb_test")
    await store.upsert("a", [0.1, 0.2, 0.3, 0.4])
    await store.upsert("b", [0.5, 0.6, 0.7, 0.8])

    results = await store.search([0.1, 0.2, 0.3, 0.4], limit=2)
    assert len(results) >= 1
    assert results[0]["memory_id"] == "a"


@pytest.mark.asyncio
async def test_lancedb_batch_upsert(tmp_path: Path) -> None:
    store = LanceDBVectorStore(tmp_path / "lancedb_batch")
    await store.batch_upsert([
        ("c", [0.9, 0.1, 0.2, 0.3], {}),
        ("d", [0.1, 0.9, 0.2, 0.3], {}),
    ])
    results = await store.search([0.9, 0.1, 0.2, 0.3], limit=3)
    assert len(results) >= 2
    ids = {r["memory_id"] for r in results}
    assert "c" in ids
    assert "d" in ids


@pytest.mark.asyncio
async def test_lancedb_delete(tmp_path: Path) -> None:
    store = LanceDBVectorStore(tmp_path / "lancedb_del")
    await store.upsert("x", [1.0, 0.0, 0.0])
    await store.upsert("y", [0.0, 1.0, 0.0])
    await store.delete("x")
    results = await store.search([1.0, 0.0, 0.0], limit=5)
    ids = {r["memory_id"] for r in results}
    assert "x" not in ids


@pytest.mark.asyncio
async def test_lancedb_empty_search(tmp_path: Path) -> None:
    store = LanceDBVectorStore(tmp_path / "lancedb_empty")
    results = await store.search([0.1, 0.2], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_lancedb_benchmark_stats(tmp_path: Path) -> None:
    store = LanceDBVectorStore(tmp_path / "lancedb_stats")
    await store.upsert("z", [0.5, 0.5, 0.5])
    stats = await store.benchmark()
    assert stats["count"] >= 1
    assert stats["table_name"] == "vectors"
