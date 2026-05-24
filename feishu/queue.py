# memoryx/feishu/queue.py
"""
SQLite 持久队列：忙碌不丢附件。

设计原则：飞书事件进来后，先入库，再处理。
哪怕 Hermes 正忙、进程重启、stream 断开，附件 metadata 和本地路径也不会丢。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .schemas import FeishuRenderJob, HermesRunState


class FeishuSQLiteQueue:
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
            CREATE TABLE IF NOT EXISTS feishu_jobs (
                job_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                user_id TEXT,
                message_id TEXT,
                card_message_id TEXT,
                state TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feishu_jobs_state_priority
            ON feishu_jobs(state, priority, created_at);
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_attachments (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                file_key TEXT,
                image_key TEXT,
                name TEXT,
                mime_type TEXT,
                size INTEGER,
                local_path TEXT,
                source_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(job_id) REFERENCES feishu_jobs(job_id) ON DELETE CASCADE
            );
            """)

            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feishu_attachments_job
            ON feishu_attachments(job_id, status);
            """)

    def enqueue(self, job: FeishuRenderJob, *, priority: int = 100) -> str:
        now = time.time()
        payload = json.dumps(job.to_dict(), ensure_ascii=False)

        with self._connect() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO feishu_jobs(
                job_id, chat_id, user_id, message_id, card_message_id,
                state, priority, payload_json, attempts, locked_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?);
            """, (
                job.job_id,
                job.chat_id,
                job.user_id,
                job.message_id,
                job.card_message_id,
                str(job.state),
                priority,
                payload,
                now,
                now,
            ))

        return job.job_id

    def claim_next(self, *, stale_after_seconds: float = 300.0) -> FeishuRenderJob | None:
        now = time.time()

        with self._connect() as conn:
            row = conn.execute("""
            SELECT *
            FROM feishu_jobs
            WHERE state IN ('queued', 'error')
              AND (locked_at IS NULL OR locked_at < ?)
            ORDER BY priority ASC, created_at ASC
            LIMIT 1;
            """, (now - stale_after_seconds,)).fetchone()

            if not row:
                return None

            conn.execute("""
            UPDATE feishu_jobs
            SET state='running', locked_at=?, attempts=attempts+1, updated_at=?
            WHERE job_id=?;
            """, (now, now, row["job_id"]))

            payload = json.loads(row["payload_json"])
            payload["state"] = HermesRunState.RUNNING
            return FeishuRenderJob.from_dict(payload)

    def update(self, job: FeishuRenderJob) -> None:
        now = time.time()

        with self._connect() as conn:
            conn.execute("""
            UPDATE feishu_jobs
            SET state=?, card_message_id=?, payload_json=?, updated_at=?, locked_at=NULL
            WHERE job_id=?;
            """, (
                str(job.state),
                job.card_message_id,
                json.dumps(job.to_dict(), ensure_ascii=False),
                now,
                job.job_id,
            ))

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("""
            SELECT state, COUNT(*) AS n
            FROM feishu_jobs
            GROUP BY state;
            """).fetchall()
        return {r["state"]: int(r["n"]) for r in rows}
