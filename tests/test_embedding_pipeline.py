from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings import EmbeddingCache, EmbeddingManager, EmbeddingRequest, VectorStore


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(index + 1)] * 4 for index, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_embedding_manager_uses_cache(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.json")
    client = FakeEmbeddingClient()
    manager = EmbeddingManager(client=client, cache=cache, batch_size=8, expected_dimension=4)

    first = await manager.embed_text("hello world")
    second = await manager.embed_text("hello world")

    assert first == second
    assert client.calls == 1


@pytest.mark.asyncio
async def test_embedding_manager_batches_requests(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "batch-cache.json")
    client = FakeEmbeddingClient()
    manager = EmbeddingManager(client=client, cache=cache, batch_size=16, expected_dimension=4)

    vectors = await manager.embed_texts(["a", "b", "c"])

    assert len(vectors) == 3
    assert client.calls == 1


@pytest.mark.asyncio
async def test_vector_store_upsert_search_delete(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "vector-store.json")
    await store.open()
    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0], {"memory_id": "m1"})
    await store.upsert("m2", [0.9, 0.1, 0.0, 0.0], {"memory_id": "m2"})

    results = await store.search([1.0, 0.0, 0.0, 0.0], limit=2)
    assert results[0]["memory_id"] == "m1"
    assert results[1]["memory_id"] == "m2"

    await store.delete("m1")
    results_after_delete = await store.search([1.0, 0.0, 0.0, 0.0], limit=5)
    assert all(item["memory_id"] != "m1" for item in results_after_delete)


@pytest.mark.asyncio
async def test_embedding_manager_tracks_freshness(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "freshness-cache.json")
    client = FakeEmbeddingClient()
    manager = EmbeddingManager(client=client, cache=cache, batch_size=8, expected_dimension=4)

    request = EmbeddingRequest(memory_id="m1", content="fresh text")
    result = await manager.embed_request(request)

    assert result.freshness_score == pytest.approx(1.0)
    assert result.dimension == 4
