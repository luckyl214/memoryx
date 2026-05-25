"""飞书全链路追踪 — 可诊断任意 job 的完整处理过程。

查询命令：
    python tools/feishu_trace.py --job-id xxx
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class FeishuTraceStore:
    """飞书事件追踪存储"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                trace_id TEXT,
                phase TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            """)
            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feishu_trace_job
            ON feishu_trace_events(job_id, created_at);
            """)
            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feishu_trace_phase
            ON feishu_trace_events(phase, created_at);
            """)

    def record(
        self,
        *,
        job_id: str,
        phase: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        """记录一个追踪事件"""
        with self._connect() as conn:
            conn.execute("""
            INSERT INTO feishu_trace_events(job_id, trace_id, phase, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (
                job_id,
                trace_id,
                phase,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False),
                time.time(),
            ))

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        """获取某个 job 的所有追踪事件"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM feishu_trace_events WHERE job_id=? ORDER BY created_at;""",
                (job_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_timeline(self, job_id: str) -> list[dict[str, Any]]:
        """获取某个 job 的时间线（按 phase 分组）"""
        events = self.get_events(job_id)
        timeline = []
        for e in events:
            timeline.append({
                "time": e["created_at"],
                "phase": e["phase"],
                "event": e["event_type"],
                "payload": json.loads(e["payload_json"]) if e["payload_json"] else {},
            })
        return timeline

    def clear_old(self, *, max_age_seconds: float = 7 * 24 * 3600) -> int:
        """清理超过 max_age_seconds 的旧追踪记录"""
        cutoff = time.time() - max_age_seconds
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM feishu_trace_events WHERE created_at < ?;",
                (cutoff,),
            )
            conn.commit()
            return result.rowcount
