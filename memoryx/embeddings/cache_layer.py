from __future__ import annotations

import asyncio
import json
from pathlib import Path


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._loaded = False
        self._data: dict[str, list[float]] = {}

    async def get(self, key: str) -> list[float] | None:
        await self._ensure_loaded()
        return self._data.get(key)

    async def set(self, key: str, vector: list[float]) -> None:
        await self._ensure_loaded()
        async with self._lock:
            self._data[key] = vector
            await self._persist()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            if self.path.exists():
                payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
                self._data = {key: [float(item) for item in value] for key, value in json.loads(payload).items()}
            self._loaded = True

    async def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, separators=(",", ":"))
        await asyncio.to_thread(self.path.write_text, payload, encoding="utf-8")
