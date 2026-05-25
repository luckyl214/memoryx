# memoryx/feishu/dedupe.py
"""
飞书事件去重：防止飞书重试造成重复卡片。

设计：
  - event_id 为主键（飞书保证唯一）
  - payload_hash 用于检测内容变更
  - 已处理事件永久记录，不设置 TTL
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path


class FeishuEventDedupe:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_event_dedupe (
                event_id TEXT PRIMARY KEY,
                message_id TEXT,
                first_seen_at REAL NOT NULL,
                payload_hash TEXT NOT NULL DEFAULT ''
            );
            """)

    def seen_or_mark(self, *, event_id: str, message_id: str | None, payload_hash: str = "") -> bool:
        """
        检查事件是否已见过。
        返回 True = 已见过（去重），False = 新事件（可处理）。
        """
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id FROM feishu_event_dedupe WHERE event_id=?;",
                (event_id,),
            ).fetchone()
            if row:
                return True
            conn.execute(
                """
                INSERT INTO feishu_event_dedupe(event_id, message_id, first_seen_at, payload_hash)
                VALUES (?, ?, ?, ?);
                """,
                (event_id, message_id, now, payload_hash),
            )
            return False
