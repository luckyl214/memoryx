from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ..events import MemoryEvent, MemoryEventType
from ..storage.sqlite_async import AsyncSQLite


class SQLitePersistedQueueManager:
    """QueueManager-compatible backend with SQLite persistence.

    Runtime dispatch still uses an in-memory asyncio.Queue for low overhead, while
    event durability, recovery and deletion are backed by SQLite instead of one
    JSON file per event.
    """

    def __init__(self, *, db_path: Path, queue_size: int, enqueue_timeout: float) -> None:
        self.db = AsyncSQLite(db_path)
        self.queue: asyncio.Queue[MemoryEvent | None] = asyncio.Queue(maxsize=queue_size)
        self.enqueue_timeout = enqueue_timeout
        self._opened = False

    async def open(self) -> None:
        if self._opened:
            return
        await self.db.open()
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS event_queue (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_queue_status_created ON event_queue(status, created_at);"
        )
        self._opened = True

    async def close(self) -> None:
        if self._opened:
            await self.db.close()
            self._opened = False

    def put_nowait(self, event: MemoryEvent | None) -> None:
        self.queue.put_nowait(event)

    async def put(self, event: MemoryEvent) -> None:
        await asyncio.wait_for(self.queue.put(event), timeout=self.enqueue_timeout)

    async def get(self) -> MemoryEvent | None:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()

    def depth(self) -> int:
        return self.queue.qsize()

    def maxsize(self) -> int:
        return self.queue.maxsize

    def can_drop(self, event: MemoryEvent) -> bool:
        return event.event_type in {MemoryEventType.ON_ASSISTANT_RESPONSE, MemoryEventType.ON_TOOL_RESULT}

    async def persist(self, event: MemoryEvent) -> None:
        await self.open()
        await self.db.execute(
            """
            INSERT INTO event_queue(event_id, payload_json, status, updated_at)
            VALUES (?, ?, 'pending', datetime('now'))
            ON CONFLICT(event_id) DO UPDATE SET
                payload_json=excluded.payload_json,
                status='pending',
                updated_at=datetime('now');
            """,
            (event.event_id, json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)),
        )

    async def delete(self, event_id: str) -> None:
        await self.open()
        await self.db.execute("DELETE FROM event_queue WHERE event_id = ?;", (event_id,))

    async def recover(self) -> list[MemoryEvent]:
        await self.open()
        rows = await self.db.fetchall(
            "SELECT payload_json FROM event_queue WHERE status = 'pending' ORDER BY created_at ASC;"
        )
        recovered: list[MemoryEvent] = []
        for row in rows:
            try:
                recovered.append(MemoryEvent.model_validate(json.loads(row["payload_json"])))
            except Exception:
                continue
        return recovered
