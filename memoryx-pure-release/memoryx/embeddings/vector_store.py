from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any


class VectorStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._opened = False
        self._data: dict[str, dict[str, Any]] = {}

    async def open(self) -> None:
        if self._opened:
            return
        async with self._lock:
            if self._opened:
                return
            if self.path.exists():
                payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
                self._data = json.loads(payload)
            self._opened = True

    async def upsert(self, memory_id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        await self.open()
        async with self._lock:
            self._data[memory_id] = {"vector": vector, "metadata": metadata}
            await self._persist()

    async def delete(self, memory_id: str) -> None:
        await self.open()
        async with self._lock:
            self._data.pop(memory_id, None)
            await self._persist()

    async def search(self, query_vector: list[float], limit: int = 10) -> list[dict[str, Any]]:
        await self.open()
        scored: list[dict[str, Any]] = []
        for memory_id, item in self._data.items():
            score = self._cosine_similarity(query_vector, [float(v) for v in item["vector"]])
            scored.append({"memory_id": memory_id, "score": score, **dict(item["metadata"])})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return dot / (left_norm * right_norm)

    async def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, separators=(",", ":"))
        await asyncio.to_thread(self.path.write_text, payload, encoding="utf-8")
