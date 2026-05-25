# memoryx/feishu/queue.py
"""
SQLite 持久队列：忙碌不丢附件。

设计原则：飞书事件进来后，先入库，再处理。
哪怕 Hermes 正忙、进程重启、stream 断开，附件 metadata 和本地路径也不会丢。

P14.1 硬化：
  - max_attempts 限制重试次数
  - 超过次数自动移入 dead_letter
  - feishu_attachments 表真正使用（双写）
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from .schemas import AttachmentRef, FeishuRenderJob, HermesRunState, VisibleState


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
            # --- feishu_jobs (P14.3: 添加 revision, visible_state, phase) ---
            conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_jobs (
                job_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                user_id TEXT,
                message_id TEXT,
                card_message_id TEXT,
                state TEXT NOT NULL,
                visible_state TEXT NOT NULL DEFAULT 'received',
                phase TEXT NOT NULL DEFAULT 'received',
                revision INTEGER NOT NULL DEFAULT 0,
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

            # --- feishu_attachments ---
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
                download_status TEXT NOT NULL DEFAULT 'pending',
                error_msg TEXT,
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

            # --- feishu_dead_letters ---
            conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_dead_letters (
                job_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                last_error TEXT,
                created_at REAL NOT NULL
            );
            """)

    def enqueue(self, job: FeishuRenderJob, *, priority: int = 100) -> str:
        """入队，同时双写 attachments"""
        now = time.time()
        payload = json.dumps(job.to_dict(), ensure_ascii=False)

        with self._connect() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO feishu_jobs(
                job_id, chat_id, user_id, message_id, card_message_id,
                state, visible_state, phase, revision, priority, payload_json, attempts, locked_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?);
            """, (
                job.job_id,
                job.chat_id,
                job.user_id,
                job.message_id,
                job.card_message_id,
                str(job.state),
                str(job.visible_state),
                job.phase,
                job.revision,
                priority,
                payload,
                now,
                now,
            ))

            # 双写 attachments
            for i, att in enumerate(job.attachments):
                att_id = f"{job.job_id}_att_{i}"
                conn.execute("""
                INSERT INTO feishu_attachments(
                    id, job_id, kind, file_key, image_key, name, mime_type,
                    size, local_path, source_message_id, status, download_status,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    att_id,
                    job.job_id,
                    att.kind,
                    att.file_key,
                    att.image_key,
                    att.name,
                    att.mime_type,
                    att.size,
                    att.local_path,
                    att.source_message_id,
                    "queued",
                    "pending",
                    json.dumps(att.extra, ensure_ascii=False),
                    now,
                    now,
                ))

        return job.job_id

    def claim_next(self, *, stale_after_seconds: float = 300.0, max_attempts: int = 3) -> FeishuRenderJob | None:
        """领取下一个 job，超过 max_attempts 的移入 DLQ"""
        now = time.time()

        with self._connect() as conn:
            # 1. 先把超过次数的 error job 移到 DLQ
            rows = conn.execute("""
            SELECT job_id, payload_json, attempts
            FROM feishu_jobs
            WHERE state='error' AND attempts >= ?;
            """, (max_attempts,)).fetchall()

            for r in rows:
                conn.execute("""
                INSERT OR REPLACE INTO feishu_dead_letters(job_id, payload_json, reason, attempts, last_error, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (r["job_id"], r["payload_json"], "max_attempts_exceeded", r["attempts"], "", now))
                conn.execute("DELETE FROM feishu_jobs WHERE job_id=?;", (r["job_id"],))

            # 2. 领取下一个
            row = conn.execute("""
            SELECT *
            FROM feishu_jobs
            WHERE state IN ('queued', 'error')
              AND attempts < ?
              AND (locked_at IS NULL OR locked_at < ?)
            ORDER BY priority ASC, created_at ASC
            LIMIT 1;
            """, (max_attempts, now - stale_after_seconds)).fetchone()

            if not row:
                return None

            conn.execute("""
            UPDATE feishu_jobs
            SET state='running', visible_state='thinking', phase='prepare', revision=revision+1, locked_at=?, attempts=attempts+1, updated_at=?
            WHERE job_id=?;
            """, (now, now, row["job_id"]))

            payload = json.loads(row["payload_json"])
            payload["state"] = HermesRunState.RUNNING
            return FeishuRenderJob.from_dict(payload)

    def update(self, job: FeishuRenderJob) -> None:
        """更新 job 状态（P14.3: 包含 revision 防乱序）"""
        now = time.time()

        with self._connect() as conn:
            conn.execute("""
            UPDATE feishu_jobs
            SET state=?, visible_state=?, phase=?, revision=?, card_message_id=?, payload_json=?, updated_at=?, locked_at=NULL
            WHERE job_id=? AND revision >= ?;
            """, (
                str(job.state),
                str(job.visible_state),
                job.phase,
                job.revision,
                job.card_message_id,
                json.dumps(job.to_dict(), ensure_ascii=False),
                now,
                job.job_id,
                job.revision,  # 只更新 >= 当前 revision 的记录
            ))

    def mark_attachment_status(self, att_id: str, *, download_status: str, local_path: str | None = None, error_msg: str | None = None) -> None:
        """更新附件下载状态"""
        now = time.time()
        with self._connect() as conn:
            if local_path is not None:
                conn.execute("""
                UPDATE feishu_attachments
                SET download_status=?, local_path=?, error_msg=?, updated_at=?
                WHERE id=?;
                """, (download_status, local_path, error_msg, now, att_id))
            else:
                conn.execute("""
                UPDATE feishu_attachments
                SET download_status=?, error_msg=?, updated_at=?
                WHERE id=?;
                """, (download_status, error_msg, now, att_id))

    async def download_attachments(self, job: FeishuRenderJob, client: "FeishuClient") -> list[AttachmentRef]:
        """下载 job 的所有待处理附件，返回更新后的 attachment refs"""
        attachments = list(job.attachments)
        pending = [(i, a) for i, a in enumerate(attachments) if a.local_path is None and (a.image_key or a.file_key)]

        if not pending:
            return attachments

        async def download_one(idx: int, att: AttachmentRef) -> AttachmentRef | Exception:
            try:
                if att.image_key:
                    local_path = await client.download_image(image_key=att.image_key)
                elif att.file_key:
                    local_path = await client.download_file(file_key=att.file_key)
                else:
                    return att

                # 更新本地路径
                att.local_path = str(local_path)
                # 更新队列中的状态
                att_id = f"{job.job_id}_att_{idx}"
                self.mark_attachment_status(att_id, download_status="downloaded", local_path=str(local_path))
                return att
            except Exception as e:
                att_id = f"{job.job_id}_att_{idx}"
                self.mark_attachment_status(att_id, download_status="failed", error_msg=str(e))
                return e

        # 并发下载
        tasks = [download_one(idx, att) for idx, att in pending]
        results = await asyncio.gather(*tasks)

        # 更新 results 到 attachments
        for i, result in enumerate(results):
            if isinstance(result, AttachmentRef):
                attachments[pending[i][0]] = result

        return attachments

    def get_attachments_for_job(self, job_id: str) -> list[dict]:
        """获取 job 的所有附件"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM feishu_attachments WHERE job_id=? ORDER BY created_at;",
                (job_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def dlq_stats(self) -> dict[str, int]:
        """DLQ 统计"""
        with self._connect() as conn:
            rows = conn.execute("""
            SELECT reason, COUNT(*) AS n
            FROM feishu_dead_letters
            GROUP BY reason;
            """).fetchall()
            return {r["reason"]: int(r["n"]) for r in rows}

    def stats(self) -> dict[str, int]:
        """队列统计"""
        with self._connect() as conn:
            rows = conn.execute("""
            SELECT state, COUNT(*) AS n
            FROM feishu_jobs
            GROUP BY state;
            """).fetchall()
            return {r["state"]: int(r["n"]) for r in rows}
