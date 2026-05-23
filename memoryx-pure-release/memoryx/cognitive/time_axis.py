from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: str | datetime | None = None) -> str:
    return _dt(value).isoformat()


def _duration(start: str | datetime, end: str | datetime) -> int:
    return max(0, int((_dt(end) - _dt(start)).total_seconds()))


class SessionTaskTracker:
    """Records session and explicit/implicit task durations from EventBus events."""

    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def on_event(self, event) -> None:
        event_type = str(getattr(event, "event_type", ""))
        payload = getattr(event, "payload", {}) or {}
        session_id = getattr(event, "session_id", None) or payload.get("session_id")
        created_at = getattr(event, "created_at", None) or payload.get("timestamp")
        if not session_id:
            return
        if event_type.endswith("on_user_message") or event_type.endswith("ON_USER_MESSAGE"):
            await self.start_session(str(session_id), _dt(created_at))
        elif event_type.endswith("on_session_end") or event_type.endswith("ON_SESSION_END"):
            await self.end_session(str(session_id), _dt(created_at))

    async def start_session(self, session_id: str, ts: datetime | None = None, *, title: str | None = None) -> None:
        now = _iso(ts)
        await self.repository.db.execute(
            """
            INSERT INTO sessions(session_id, title, start_time, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(session_id) DO NOTHING;
            """,
            (session_id, title, now, now, now),
        )

    async def end_session(self, session_id: str, ts: datetime | None = None) -> int:
        end = _iso(ts)
        row = await self.repository.db.fetchone("SELECT start_time FROM sessions WHERE session_id = ?;", (session_id,))
        if not row:
            await self.start_session(session_id, _dt(ts))
            row = await self.repository.db.fetchone("SELECT start_time FROM sessions WHERE session_id = ?;", (session_id,))
        seconds = _duration(row["start_time"], end) if row else 0
        await self.repository.db.execute(
            """
            UPDATE sessions
            SET end_time = ?, duration_seconds = ?, status = 'ended', updated_at = datetime('now')
            WHERE session_id = ?;
            """,
            (end, seconds, session_id),
        )
        return seconds

    async def start_task(
        self,
        *,
        title: str,
        session_id: str | None = None,
        entity_id: str | None = None,
        task_type: str = "generic",
        ts: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        task_id = uuid4().hex
        now = _iso(ts)
        await self.repository.db.execute(
            """
            INSERT INTO tasks(task_id, session_id, entity_id, title, task_type, start_time, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?);
            """,
            (task_id, session_id, entity_id, title, task_type, now, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return task_id

    async def end_task(self, task_id: str, ts: datetime | None = None, *, source: str = "event") -> int:
        row = await self.repository.db.fetchone("SELECT * FROM tasks WHERE task_id = ?;", (task_id,))
        if not row:
            return 0
        end = _iso(ts)
        seconds = _duration(row["start_time"], end)
        await self.repository.db.execute(
            """
            UPDATE tasks
            SET end_time = ?, duration_seconds = ?, status = 'ended', updated_at = datetime('now')
            WHERE task_id = ?;
            """,
            (end, seconds, task_id),
        )
        await self.repository.db.execute(
            """
            INSERT INTO task_durations(id, task_id, session_id, entity_id, start_time, end_time, duration_seconds, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (uuid4().hex, task_id, row["session_id"], row["entity_id"], row["start_time"], end, seconds, source),
        )
        return seconds


class TaskDurationEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def duration_for_entity(
        self,
        *,
        entity_id: str | None = None,
        entity_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        task_type: str | None = None,
    ) -> dict[str, Any]:
        resolved_entity_id = entity_id or await self._resolve_entity_id(entity_name)
        clauses = []
        params: list[Any] = []
        if resolved_entity_id:
            clauses.append("entity_id = ?")
            params.append(resolved_entity_id)
        if start:
            clauses.append("end_time >= ?")
            params.append(_iso(start))
        if end:
            clauses.append("start_time <= ?")
            params.append(_iso(end))
        if task_type:
            clauses.append("task_id IN (SELECT task_id FROM tasks WHERE task_type = ?)")
            params.append(task_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        row = await self.repository.db.fetchone(
            f"SELECT COALESCE(SUM(duration_seconds), 0) AS total, COUNT(*) AS cnt FROM task_durations {where};",
            tuple(params),
        )
        count = int(row["cnt"] if row else 0)
        return {
            "entity_id": resolved_entity_id,
            "total_seconds": int(row["total"] if row else 0),
            "count": count,
            "inferred": False,
            "confidence_score": 1.0 if count else 0.0,
        }

    async def top_time_spent(
        self,
        *,
        start: datetime,
        end: datetime,
        group_by: str = "entity",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if group_by not in {"entity", "session", "task"}:
            group_by = "entity"
        column = {"entity": "entity_id", "session": "session_id", "task": "task_id"}[group_by]
        rows = await self.repository.db.fetchall(
            f"""
            SELECT {column} AS key, SUM(duration_seconds) AS total_seconds, COUNT(*) AS count
            FROM task_durations
            WHERE end_time >= ? AND start_time <= ?
            GROUP BY {column}
            ORDER BY total_seconds DESC
            LIMIT ?;
            """,
            (_iso(start), _iso(end), limit),
        )
        return [dict(r) for r in rows]

    async def _resolve_entity_id(self, entity_name: str | None) -> str | None:
        if not entity_name:
            return None
        row = await self.repository.db.fetchone(
            "SELECT id FROM entities WHERE normalized_name = lower(?) OR name = ? ORDER BY confidence_score DESC LIMIT 1;",
            (entity_name.strip(), entity_name.strip()),
        )
        return str(row["id"]) if row else None


class EntityTimelineEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def timeline(
        self,
        *,
        entity_id: str,
        include_opinion_shifts: bool = True,
        include_tasks: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        mem_rows = await self.repository.db.fetchall(
            """
            SELECT m.id, m.memory_type, m.content, m.valid_from, m.updated_at, me.role
            FROM memory_entities me JOIN memories m ON m.id = me.memory_id
            WHERE me.entity_id = ? AND m.active_state = 'active'
            ORDER BY COALESCE(m.valid_from, m.updated_at) ASC
            LIMIT ?;
            """,
            (entity_id, limit),
        )
        for r in mem_rows:
            item = dict(r)
            items.append({"kind": "memory", "time": item.get("valid_from") or item.get("updated_at"), **item})
        if include_tasks:
            task_rows = await self.repository.db.fetchall(
                "SELECT * FROM task_durations WHERE entity_id = ? ORDER BY start_time ASC LIMIT ?;",
                (entity_id, limit),
            )
            for r in task_rows:
                items.append({"kind": "task_duration", "time": r["start_time"], **dict(r)})
        if include_opinion_shifts:
            shift_rows = await self.repository.db.fetchall(
                "SELECT * FROM opinion_shifts WHERE entity_id = ? ORDER BY from_time ASC LIMIT ?;",
                (entity_id, limit),
            )
            for r in shift_rows:
                items.append({"kind": "opinion_shift", "time": r["to_time"], **dict(r)})
        items.sort(key=lambda x: str(x.get("time") or ""))
        return items[:limit]
