"""P7: SQLiteQueueManager — 可选 SQLite-backed 事件队列。

替代默认 file queue（一事件一文件），用于高性能场景。
配置：event_queue_backend = "file" | "sqlite"（config.py）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass
class QueueItem:
    id: str
    event_type: str
    payload_json: str
    status: str = "pending"  # pending / processing / done / failed
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0


class SQLiteQueueManager:
    """SQLite 事件队列管理器。

    特性：
    - 原子入队/出队（事务）
    - 状态追踪：pending → processing → done/failed
    - 失败重试（最多 3 次）
    - 死信队列（重试耗尽 → dead）
    - 与 file queue 兼容的 enqueue/dequeue 接口
    """

    MAX_RETRIES: int = 3

    def __init__(self, *, db, table_name: str = "event_queue") -> None:
        self.db = db
        self.table_name = table_name

    async def ensure_table(self) -> None:
        await self.db.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{{}}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at REAL NOT NULL
            );
        """)
        await self.db.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_status
            ON {self.table_name}(status, created_at);
        """)

    async def enqueue(self, event_type: str, payload: dict[str, Any]) -> str:
        item_id = uuid4().hex
        now = time.time()
        await self.db.execute(
            f"INSERT INTO {self.table_name}(id, event_type, payload_json, status, created_at, retry_count, updated_at) VALUES (?, ?, ?, 'pending', ?, 0, ?);",
            (item_id, event_type, json.dumps(payload, ensure_ascii=False), now, now),
        )
        return item_id

    async def dequeue(self, limit: int = 10) -> list[QueueItem]:
        """原子出队：批量获取 pending 事件并标记为 processing。"""
        now = time.time()
        rows = await self.db.fetchall(
            f"SELECT id, event_type, payload_json, retry_count FROM {self.table_name} WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?;",
            (limit,),
        )
        if not rows:
            return []

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        await self.db.execute(
            f"UPDATE {self.table_name} SET status = 'processing', updated_at = ? WHERE id IN ({placeholders});",
            (now, *ids),
        )

        return [
            QueueItem(
                id=row["id"],
                event_type=row["event_type"],
                payload_json=row["payload_json"],
                status="processing",
                retry_count=row["retry_count"],
            )
            for row in rows
        ]

    async def mark_done(self, item_id: str) -> None:
        await self.db.execute(
            f"UPDATE {self.table_name} SET status = 'done', updated_at = ? WHERE id = ?;",
            (time.time(), item_id),
        )

    async def mark_failed(self, item_id: str, error: str) -> None:
        now = time.time()
        row = await self.db.fetchone(
            f"SELECT retry_count FROM {self.table_name} WHERE id = ?;",
            (item_id,),
        )
        if not row:
            return
        retries = int(row["retry_count"]) + 1
        if retries > self.MAX_RETRIES:
            await self.db.execute(
                f"UPDATE {self.table_name} SET status = 'dead', retry_count = ?, last_error = ?, updated_at = ? WHERE id = ?;",
                (retries, error, now, item_id),
            )
        else:
            await self.db.execute(
                f"UPDATE {self.table_name} SET status = 'pending', retry_count = ?, last_error = ?, updated_at = ? WHERE id = ?;",
                (retries, error, now, item_id),
            )

    async def stats(self) -> dict[str, int]:
        by_status = await self.db.fetchall(
            f"SELECT status, COUNT(*) as cnt FROM {self.table_name} GROUP BY status;"
        )
        return {row["status"]: row["cnt"] for row in by_status}
