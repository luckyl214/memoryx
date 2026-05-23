from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings import EmbeddingQueueWorker, EmbeddingRequest, VectorStore


class FailingEmbeddingManager:
    async def embed_request(self, request: EmbeddingRequest):
        raise RuntimeError("boom")


class FakeEmbeddingManager:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def embed_request(self, request: EmbeddingRequest):
        self.requests.append(request.memory_id)
        return type(
            "EmbeddingResult",
            (),
            {
                "memory_id": request.memory_id,
                "vector": [1.0, 0.0, 0.0, 0.0],
                "dimension": 4,
                "freshness_score": 1.0,
                "metadata": {"content": request.content},
            },
        )()


@pytest.mark.asyncio
async def test_queue_worker_persists_jobs(tmp_path: Path) -> None:
    manager = FakeEmbeddingManager()
    store = VectorStore(tmp_path / "worker-vectors.json")
    await store.open()
    worker = EmbeddingQueueWorker(
        queue_path=tmp_path / "embedding-queue.json",
        failed_queue_path=tmp_path / "embedding-failed.json",
        manager=manager,
        vector_store=store,
    )

    await worker.enqueue(EmbeddingRequest(memory_id="m1", content="hello"))
    await worker.run_once()

    results = await store.search([1.0, 0.0, 0.0, 0.0], limit=1)
    assert results[0]["memory_id"] == "m1"

    persisted = (tmp_path / "embedding-queue.json").read_text(encoding="utf-8")
    assert persisted.strip().startswith("[")


@pytest.mark.asyncio
async def test_queue_worker_recovers_failed_jobs(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "failed-worker-vectors.json")
    await store.open()
    worker = EmbeddingQueueWorker(
        queue_path=tmp_path / "embedding-queue.json",
        failed_queue_path=tmp_path / "embedding-failed.json",
        manager=FailingEmbeddingManager(),
        vector_store=store,
    )

    await worker.enqueue(EmbeddingRequest(memory_id="m2", content="boom"))
    with pytest.raises(RuntimeError):
        await worker.run_once()

    failed_payload = (tmp_path / "embedding-failed.json").read_text(encoding="utf-8")
    assert "m2" in failed_payload
