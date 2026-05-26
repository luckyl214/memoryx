from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from memoryx.api.dependencies import get_repository, get_task_service
from memoryx.services.task_service import TaskService


router = APIRouter(prefix="/v1/cognitive", tags=["cognitive-tasks"])


class TaskStartRequest(BaseModel):
    session_id: str = "default"
    entity_id: str = "general"
    task_type: str = "conversation"
    title: str = "Hermes session"
    source: str = "hermes"


class TaskEndRequest(BaseModel):
    session_id: str = "default"
    entity_id: str = "general"
    status: str = "done"
    summary: str = ""
    source: str = "hermes"


class TaskDurationsQuery(BaseModel):
    session_id: str | None = None
    entity_id: str | None = None
    task_type: str | None = None
    since: str | None = None
    until: str | None = None


class EntityTimelineQuery(BaseModel):
    entity_id: str = "general"
    since: str | None = None
    until: str | None = None
    limit: int = 50


@router.post("/task/start-v2")
async def task_start_v2(
    body: TaskStartRequest,
    service: TaskService = Depends(get_task_service),
) -> dict:
    result = await service.start_task(**body.model_dump())
    return {
        "task_id": result.task_id,
        "session_id": result.session_id,
        "status": result.status,
        "started_at": result.started_at,
    }


@router.post("/task/end-v2")
async def task_end_v2(
    body: TaskEndRequest,
    service: TaskService = Depends(get_task_service),
) -> dict:
    result = await service.end_task(**body.model_dump())
    return {
        "ended": result.ended,
        "reason": result.reason,
        "task_id": result.task_id,
        "session_id": result.session_id,
        "entity_id": result.entity_id,
        "status": result.status,
        "duration_seconds": result.duration_seconds,
        "ended_at": result.ended_at,
    }


@router.post("/task/durations-v2")
async def task_durations_v2(
    body: TaskDurationsQuery,
    repo=Depends(get_repository),
) -> dict:
    wheres = ["1=1"]
    params = []

    if body.session_id:
        wheres.append("session_id = ?")
        params.append(body.session_id)
    if body.entity_id:
        wheres.append("entity_id = ?")
        params.append(body.entity_id)
    if body.task_type:
        wheres.append("json_extract(metadata_json, '$.task_type') = ?")
        params.append(body.task_type)
    if body.since:
        wheres.append("start_time >= ?")
        params.append(body.since)
    if body.until:
        wheres.append("end_time <= ?")
        params.append(body.until)

    where_clause = " AND ".join(wheres)

    stats = await repo.db.fetchone(
        f"""
        SELECT COUNT(*) as total_tasks,
               COALESCE(SUM(duration_seconds), 0) as total_seconds,
               COALESCE(AVG(duration_seconds), 0) as avg_seconds
        FROM task_durations
        WHERE {where_clause};
        """,
        tuple(params),
    )

    rows = await repo.db.fetchall(
        f"""
        SELECT entity_id, COUNT(*) as count, SUM(duration_seconds) as total_seconds
        FROM task_durations
        WHERE {where_clause}
        GROUP BY entity_id
        ORDER BY total_seconds DESC;
        """,
        tuple(params),
    )

    return {
        "summary": {
            "total_tasks": stats["total_tasks"] if stats else 0,
            "total_seconds": stats["total_seconds"] if stats else 0,
            "avg_seconds": round(stats["avg_seconds"], 1) if stats else 0,
        },
        "by_entity": [dict(r) for r in rows] if rows else [],
    }


@router.post("/entity/timeline-v2")
async def entity_timeline_v2(
    body: EntityTimelineQuery,
    repo=Depends(get_repository),
) -> dict:
    wheres = ["entity_id = ?"]
    params = [body.entity_id]

    if body.since:
        wheres.append("start_time >= ?")
        params.append(body.since)
    if body.until:
        wheres.append("end_time <= ?")
        params.append(body.until)

    rows = await repo.db.fetchall(
        f"""
        SELECT task_id, session_id, task_type, title, start_time, end_time,
               duration_seconds, status, metadata_json
        FROM tasks
        WHERE {' AND '.join(wheres)}
        ORDER BY start_time DESC
        LIMIT ?;
        """,
        tuple(params) + (body.limit,),
    )

    return {
        "entity_id": body.entity_id,
        "entries": [
            {
                "task_id": r["task_id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "task_type": r["task_type"],
                "status": r["status"],
                "started_at": r["start_time"],
                "ended_at": r["end_time"],
                "duration_seconds": r["duration_seconds"],
            }
            for r in rows
        ],
        "count": len(rows),
    }
