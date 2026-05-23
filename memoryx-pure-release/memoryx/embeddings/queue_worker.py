from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .models import EmbeddingRequest


class EmbeddingQueueWorker:
    def __init__(
        self,
        *,
        queue_path: Path,
        failed_queue_path: Path,
        manager,
        vector_store,
    ) -> None:
        self.queue_path = queue_path
        self.failed_queue_path = failed_queue_path
        self.manager = manager
        self.vector_store = vector_store
        self._lock = asyncio.Lock()

    async def enqueue(self, request: EmbeddingRequest) -> None:
        async with self._lock:
            queue = await self._load(self.queue_path)
            queue.append(asdict(request))
            await self._save(self.queue_path, queue)

    async def run_once(self) -> bool:
        async with self._lock:
            queue = await self._load(self.queue_path)
            if not queue:
                await self._save(self.queue_path, [])
                return False
            item = queue.pop(0)
            await self._save(self.queue_path, queue)

        request = EmbeddingRequest(**item)
        try:
            result = await self.manager.embed_request(request)
            await self.vector_store.upsert(result.memory_id, result.vector, {"memory_id": result.memory_id, **result.metadata})
            return True
        except Exception:
            failed = await self._load(self.failed_queue_path)
            failed.append(item)
            await self._save(self.failed_queue_path, failed)
            raise

    async def _load(self, path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        payload = await asyncio.to_thread(path.read_text, encoding="utf-8")
        if not payload.strip():
            return []
        return list(json.loads(payload))

    async def _save(self, path: Path, items: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        await asyncio.to_thread(path.write_text, payload, encoding="utf-8")
