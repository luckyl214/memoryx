from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskStartResult:
    task_id: str
    session_id: str
    status: str
    started_at: str


@dataclass(slots=True)
class TaskEndResult:
    ended: bool
    reason: str = ""
    task_id: str | None = None
    session_id: str | None = None
    entity_id: str | None = None
    status: str | None = None
    duration_seconds: int = 0
    ended_at: str | None = None


class TaskService:
    """
    Task lifecycle service.

    替代 p11_routes.py 中直接 sqlite3.connect 的实现。
    """

    def __init__(self, *, repository: Any) -> None:
        self.repository = repository

    async def start_task(
        self,
        *,
        session_id: str = "default",
        entity_id: str = "general",
        task_type: str = "conversation",
        title: str = "Hermes session",
        source: str = "hermes",
    ) -> TaskStartResult:
        task_id = uuid4().hex
        now = utc_now_iso()

        async with self.repository.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO tasks(
                    task_id, session_id, entity_id, task_type, title,
                    status, start_time, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?);
                """,
                (
                    task_id,
                    session_id,
                    entity_id,
                    task_type,
                    title,
                    now,
                    now,
                    now,
                    json.dumps({"source": source}, ensure_ascii=False, sort_keys=True),
                ),
            )

        return TaskStartResult(
            task_id=task_id,
            session_id=session_id,
            status="running",
            started_at=now,
        )

    async def end_task(
        self,
        *,
        session_id: str = "default",
        entity_id: str = "general",
        status: str = "done",
        summary: str = "",
        source: str = "hermes",
    ) -> TaskEndResult:
        now = utc_now_iso()

        task = await self.repository.db.fetchone(
            """
            SELECT task_id, session_id, entity_id, task_type, title, start_time
            FROM tasks
            WHERE session_id = ? AND entity_id = ? AND status = 'running'
            ORDER BY start_time DESC
            LIMIT 1;
            """,
            (session_id, entity_id),
        )

        if not task:
            return TaskEndResult(
                ended=False,
                reason="no_running_task_found",
                session_id=session_id,
                entity_id=entity_id,
            )

        task_id = str(task["task_id"])
        started_at = str(task["start_time"])
        duration = self._duration_seconds(started_at, now)
        duration_id = uuid4().hex

        async with self.repository.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, end_time = ?, duration_seconds = ?, updated_at = ?,
                    metadata_json = ?
                WHERE task_id = ?;
                """,
                (
                    status,
                    now,
                    duration,
                    now,
                    json.dumps(
                        {"summary": summary, "source": source},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    task_id,
                ),
            )

            conn.execute(
                """
                INSERT INTO task_durations(
                    id, task_id, session_id, entity_id,
                    start_time, end_time, duration_seconds, source, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    duration_id,
                    task_id,
                    session_id,
                    entity_id,
                    started_at,
                    now,
                    duration,
                    source,
                    json.dumps(
                        {"summary": summary, "task_type": task["task_type"]},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

        return TaskEndResult(
            ended=True,
            task_id=task_id,
            session_id=session_id,
            entity_id=entity_id,
            status=status,
            duration_seconds=duration,
            ended_at=now,
        )

    def _duration_seconds(self, start_iso: str, end_iso: str) -> int:
        try:
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            return max(0, int((end_dt - start_dt).total_seconds()))
        except Exception:
            return 0
