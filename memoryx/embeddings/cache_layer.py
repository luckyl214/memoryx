"""P0-F: 有序字典 LRU 缓存 + 原子写盘 + 批量持久化。

- OrderedDict LRU，max_entries 默认 20000
- persist_every 默认 32（攒够 N 次新写入才写盘）
- tmp file + os.replace 原子写盘
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path


class EmbeddingCache:
    def __init__(
        self,
        path: Path,
        *,
        max_entries: int = 20000,
        persist_every: int = 32,
    ) -> None:
        self.path = path
        self.max_entries = max_entries
        self.persist_every = persist_every
        self._lock = asyncio.Lock()
        self._loaded = False
        self._data: OrderedDict[str, list[float]] = OrderedDict()
        self._dirty_count: int = 0

    async def get(self, key: str) -> list[float] | None:
        await self._ensure_loaded()
        async with self._lock:
            value = self._data.get(key)
            if value is not None:
                # Move to end (LRU promotion)
                self._data.move_to_end(key)
            return value

    async def set(self, key: str, vector: list[float]) -> None:
        await self._ensure_loaded()
        async with self._lock:
            # LRU eviction
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = vector
            else:
                while len(self._data) >= self.max_entries:
                    self._data.popitem(last=False)  # FIFO evict
                self._data[key] = vector
                self._dirty_count += 1

            # Batch persist: only write to disk every persist_every new entries
            if self._dirty_count >= self.persist_every:
                await self._persist()
                self._dirty_count = 0

    async def flush(self) -> None:
        """Force persist all pending writes to disk."""
        async with self._lock:
            if self._dirty_count > 0:
                await self._persist()
                self._dirty_count = 0

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            if self.path.exists():
                payload = await asyncio.to_thread(
                    self.path.read_text, encoding="utf-8"
                )
                loaded = json.loads(payload)
                self._data = OrderedDict(
                    (key, [float(item) for item in value])
                    for key, value in loaded.items()
                )
                # Enforce max_entries on load
                while len(self._data) > self.max_entries:
                    self._data.popitem(last=False)
            self._loaded = True

    async def _persist(self) -> None:
        """Atomic write: tmp file + os.replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {k: v for k, v in self._data.items()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".embedding_cache_", suffix=".tmp"
        )
        try:
            await asyncio.to_thread(os.write, tmp_fd, payload.encode("utf-8"))
            await asyncio.to_thread(os.fsync, tmp_fd)
        finally:
            await asyncio.to_thread(os.close, tmp_fd)
        await asyncio.to_thread(os.replace, tmp_path, str(self.path))
