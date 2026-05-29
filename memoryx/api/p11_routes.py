from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from memoryx.cognitive.guarded_generation import CognitiveGuard
from memoryx.cognitive.narrative_reflection import NarrativeReflectionEngine
from memoryx.cognitive.trust import MemoryTrustScorer


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class VerifyAnswerRequest(BaseModel):
    question: str
    answer: str
    session_id: str | None = None
    store: bool = True


class EvaluateActionRequest(BaseModel):
    action_text: str
    intent: str | None = None
    session_id: str | None = None
    store: bool = True


class NarrativeRequest(BaseModel):
    window_start: str
    window_end: str
    session_id: str | None = None
    entity_id: str | None = None
    reflection_type: str = "periodic"
    store: bool = True


class CognitiveContextRequest(BaseModel):
    query: str
    session_id: str | None = None
    limit: int = 8
    include_lessons: bool = True
    include_safety_contract: bool = True


class MemoryAutoStoreRequest(BaseModel):
    session_id: str = "default"
    user_message: str = ""
    assistant_response: str = ""
    source: str = "hermes.post_llm_call"


class ToolResultRequest(BaseModel):
    session_id: str = "default"
    tool_name: str = ""
    result: str = ""
    source: str = "hermes.post_tool_call"


# ── P15.2: Task lifecycle request models ──

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


# ---------------------------------------------------------------------------
# Trust scorer singleton
# ---------------------------------------------------------------------------

_trust_scorer = MemoryTrustScorer()


# ---------------------------------------------------------------------------
# Source type inference
# ---------------------------------------------------------------------------

_EXPLICIT_MARKERS = [
    "记住",
    "我的偏好",
    "我喜欢",
    "我不喜欢",
    "以后",
    "从现在开始",
    "你要记住",
]


def _infer_source_type(user_message: str, assistant_response: str) -> str:
    """Determine source_type from the user's message content."""
    for marker in _EXPLICIT_MARKERS:
        if marker in user_message:
            return "user_explicit"
    return "agent_inferred"


# ---------------------------------------------------------------------------
# Retrieval compatibility adapter
# ---------------------------------------------------------------------------

async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def _call_retrieval_any(
    retrieval: Any,
    *,
    query: str,
    session_id: str | None,
    limit: int = 8,
    include_lessons: bool = True,
) -> list[Any]:
    """Call whatever retrieval object the current app wiring provides."""

    call_specs = [
        ("search", {"query": query, "query_vector": [], "session_id": session_id, "limit": limit, "include_lessons": include_lessons}),
        ("search", {"q": query, "query_vector": [], "session_id": session_id, "limit": limit}),
        ("retrieve", {"query": query, "session_id": session_id, "limit": limit}),
        ("hybrid_search", {"query": query, "session_id": session_id, "limit": limit}),
        ("query", {"query": query, "session_id": session_id, "limit": limit}),
    ]

    for method_name, kwargs in call_specs:
        method = getattr(retrieval, method_name, None)
        if not callable(method):
            continue
        try:
            result = await _maybe_await(method(**{k: v for k, v in kwargs.items() if v is not None}))
            return _normalize_retrieval_results(result)
        except TypeError:
            continue

    results = await _fallback_retrieval(retrieval, query=query, session_id=session_id, limit=limit)
    return results


async def _fallback_retrieval(
    retrieval: Any,
    *,
    query: str,
    session_id: str | None,
    limit: int = 8,
) -> list[Any]:
    """Last-resort: unwrap wrappers or return empty."""
    if retrieval is None:
        return []

    for attr in ("query_api", "retriever", "engine", "hybrid_retrieval", "retrieval_engine"):
        inner = getattr(retrieval, attr, None)
        if inner is not None and inner is not retrieval:
            try:
                return await _call_retrieval_any(
                    inner,
                    query=query,
                    session_id=session_id,
                    limit=limit,
                    include_lessons=True,
                )
            except Exception:
                pass

    return []


async def _context_via_repo(
    repo: Any,
    *,
    query: str,
    limit: int = 8,
    include_lessons: bool = True,
) -> list[Any]:
    """Direct fallback: use repository to search memories without query_api."""
    if repo is None:
        return []
    try:
        import sqlite3
        conn = sqlite3.connect(repo.db.db_path if hasattr(repo.db, 'db_path') else None)
        if conn is None:
            conn = repo.db._require_conn()
    except Exception:
        return []

    try:
        patterns = _cjk_like_patterns(query)
        placeholders = " OR ".join(f"content LIKE ?" for _ in patterns)
        sql = f"""
        SELECT id, memory_type, content, importance_score, created_at,
               source_type, verification_status, trust_score
        FROM memories
        WHERE active_state = 'active'
          AND ({placeholders})
        ORDER BY importance_score DESC, created_at DESC
        LIMIT ?
        """
        cursor = conn.execute(sql, (*patterns, limit))
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "memory_type": r[1],
                "content": r[2],
                "score": r[3],
                "created_at": r[4],
                "source_type": r[5] or "unknown",
                "verification_status": r[6] or "unverified",
                "trust_score": r[7] or 0.5,
            }
            for r in rows
        ]
    except Exception:
        return []


def _first_word(s: str) -> str:
    """Return the first whitespace-delimited word, or the first 3 CJK chars for Chinese queries."""
    if not s.strip():
        return ""
    parts = s.split(maxsplit=1)
    if len(parts) > 1:
        return parts[0]
    # Single token with no whitespace — probably Chinese; use first 3 chars
    return s[:3]


def _cjk_like_patterns(query: str) -> list[str]:
    """Generate LIKE patterns for CJK queries where whitespace split is insufficient.

    For a query like '回答偏好', produces patterns that match individual character
    occurrences in content (e.g. '%答%' finds '回答' inside '简洁但有结构的回答').
    """
    patterns = [f"%{query}%"]
    if not query.strip():
        return patterns

    parts = query.split()
    if len(parts) > 1:
        # Multi-word query — already handled by _first_word
        return patterns

    # Single token — check if it's CJK
    cjk_count = sum(1 for ch in query if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    if cjk_count <= 1:
        return patterns

    # For CJK queries, add individual character patterns
    chars = list(query)
    # Add every 2nd char to catch common word boundaries
    for i in range(1, min(len(chars), 5)):
        patterns.append(f"%{chars[i]}%")

    return patterns


def _normalize_retrieval_results(result: Any) -> list[Any]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, tuple):
        return list(result)
    if isinstance(result, dict):
        for key in ("results", "memories", "items", "data"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        return [result]
    for attr in ("results", "memories", "items"):
        value = getattr(result, attr, None)
        if isinstance(value, list):
            return value
    return [result]


def _item_get(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _format_context_block(
    *,
    query: str,
    results: list[Any],
    include_safety_contract: bool = True,
) -> str:
    lines: list[str] = []

    if include_safety_contract:
        lines.extend([
            "MemoryX Safety Contract:",
            "- Use MemoryX as trusted long-term memory, but do not invent unsupported facts.",
            "- Treat LESSON memories as high-priority behavioral constraints.",
            "- If a claim is unsupported or contradicted, warn or verify before acting.",
            "",
        ])

    lines.append("MemoryX Retrieved Context:")

    if not results:
        lines.append("- No relevant memory found.")
        return "\n".join(lines)

    for idx, item in enumerate(results[:8], 1):
        content = (
            _item_get(item, "content")
            or _item_get(item, "text")
            or _item_get(item, "summary")
            or str(item)
        )
        memory_type = _item_get(item, "memory_type") or _item_get(item, "type") or "MEMORY"
        score = _item_get(item, "score") or _item_get(item, "final_score") or _item_get(item, "similarity") or ""
        memory_id = _item_get(item, "id") or _item_get(item, "memory_id") or ""

        prefix = f"{idx}. [{memory_type}]"
        if memory_id:
            prefix += f" {memory_id}"
        if score != "":
            prefix += f" score={score}"

        lines.append(f"{prefix}\n   {str(content)[:700]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lazy dependency resolution
# ---------------------------------------------------------------------------

async def _resolve(value_or_factory):
    if callable(value_or_factory):
        value = value_or_factory()
        if hasattr(value, "__await__"):
            return await value
        return value
    return value_or_factory


def create_p11_router(
    *,
    repository=None,
    retrieval_engine=None,
    lesson_policy=None,
    get_repository: Callable[[], Any | Awaitable[Any]] | None = None,
    get_retrieval_engine: Callable[[], Any | Awaitable[Any]] | None = None,
    get_lesson_policy: Callable[[], Any | Awaitable[Any]] | None = None,
    prefix: str = "/v1/cognitive",
) -> APIRouter:
    """Create P11 routes with lazy dependency resolution."""

    router = APIRouter(prefix=prefix, tags=["cognitive"])

    async def repo_dep():
        repo = await _resolve(get_repository) if get_repository is not None else repository
        if repo is None:
            raise HTTPException(503, "repository not configured")
        return repo

    async def retrieval_dep():
        if get_retrieval_engine is not None:
            return await _resolve(get_retrieval_engine)
        return retrieval_engine

    async def lesson_dep():
        if get_lesson_policy is not None:
            return await _resolve(get_lesson_policy)
        return lesson_policy

    @router.post("/verify-answer")
    async def verify_answer(body: VerifyAnswerRequest) -> dict:
        repo = await repo_dep()
        guard = CognitiveGuard(
            repository=repo,
            retrieval_engine=await retrieval_dep(),
            lesson_policy=await lesson_dep(),
        )
        result = await guard.verify_answer(
            question=body.question,
            answer=body.answer,
            session_id=body.session_id,
            store=body.store,
        )
        return {
            "should_block": result.should_block,
            "guard_block": result.guard_block,
            "verification": result.verification.to_dict(),
        }

    @router.post("/evaluate-action")
    async def evaluate_action(body: EvaluateActionRequest) -> dict:
        repo = await repo_dep()
        guard = CognitiveGuard(
            repository=repo,
            retrieval_engine=await retrieval_dep(),
            lesson_policy=await lesson_dep(),
        )
        result = await guard.evaluate_action(
            action_text=body.action_text,
            intent=body.intent,
            session_id=body.session_id,
            store=body.store,
        )
        return {
            "should_block": result.should_block,
            "requires_user": result.requires_user,
            "guard_block": result.guard_block,
            "enforcement": result.enforcement.to_dict(),
        }

    @router.post("/narrative-reflection")
    async def narrative_reflection(body: NarrativeRequest) -> dict:
        if body.window_start >= body.window_end:
            raise HTTPException(400, "window_start must be earlier than window_end")
        repo = await repo_dep()
        narrative = NarrativeReflectionEngine(repository=repo)
        result = await narrative.generate(
            window_start=body.window_start,
            window_end=body.window_end,
            session_id=body.session_id,
            entity_id=body.entity_id,
            reflection_type=body.reflection_type,
            store=body.store,
        )
        return result.to_dict()

    @router.post("/context")
    async def cognitive_context(
        body: CognitiveContextRequest,
        retrieval: Any = Depends(retrieval_dep),
        repo: Any = Depends(repo_dep),
    ) -> dict:
        """Build a context block from MemoryX for Hermes pre_llm_call context injection.

        P15.1: Trust-scoring filters out low-confidence agent_reflection/contradicted
        memories so they don't pollute the LLM context.
        """
        results = await _call_retrieval_any(
            retrieval,
            query=body.query,
            session_id=body.session_id,
            limit=body.limit,
            include_lessons=body.include_lessons,
        )

        # Fallback: if retrieval returned nothing useful, use repo directly
        if not results:
            results = await _context_via_repo(
                repo,
                query=body.query,
                limit=body.limit,
                include_lessons=body.include_lessons,
            )

        # ── P15.1: Filter through MemoryTrustScorer ──
        filtered = []
        for item in results:
            if isinstance(item, dict):
                data = item
            elif hasattr(item, "__dataclass_fields__"):
                # Slotted dataclass — extract fields explicitly
                import dataclasses
                data = {f.name: getattr(item, f.name) for f in dataclasses.fields(item)}
            elif hasattr(item, "__dict__"):
                data = dict(item.__dict__)
            else:
                data = {"content": str(item)}
            decision = _trust_scorer.score(data)
            if decision.should_inject:
                data["trust_score"] = decision.trust_score
                data["trust_reason"] = decision.reason
                filtered.append(data)

        results = filtered

        context_block = _format_context_block(
            query=body.query,
            results=results,
            include_safety_contract=body.include_safety_contract,
        )

        return {
            "context_block": context_block,
            "results_count": len(results),
            "session_id": body.session_id,
        }

    @router.post("/auto-store")
    async def memory_auto_store(body: MemoryAutoStoreRequest) -> dict:
        """Auto-store a conversation turn as EPISODIC memory.

        P15.1: Writes source_type, verification_status, trust_score from trust scorer.
        """
        repo = await repo_dep()
        if not body.user_message and not body.assistant_response:
            return {"stored": False, "reason": "no content"}

        import hashlib, json, uuid
        from datetime import datetime, timezone

        content = f"User: {body.user_message}\nAssistant: {body.assistant_response}"
        mem_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()
        chk = hashlib.sha256(content.encode()).hexdigest()

        # ── P15.1: Infer source_type from user message ──
        source_type = _infer_source_type(body.user_message or "", body.assistant_response or "")
        verification_status = "verified" if source_type == "user_explicit" else "unverified"

        # Compute trust score for this new memory
        trust_data = {
            "source_type": source_type,
            "verification_status": verification_status,
            "confidence_score": 0.8,
            "importance_score": 0.4,
        }
        decision = _trust_scorer.score(trust_data)
        trust_score = decision.trust_score

        async with repo.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memories(
                    id, memory_type, content, content_hash, checksum,
                    importance_score, confidence_score, active_state,
                    valid_from, created_at, updated_at, metadata_json,
                    source_type, verification_status, trust_score
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mem_id, "EPISODIC", content, chk, chk,
                    0.4, 0.8, "active",
                    now_iso, now_iso, now_iso, json.dumps({
                        "session_id": body.session_id or "default",
                        "source": body.source,
                    }),
                    source_type, verification_status, trust_score,
                ),
            )
        return {"stored": True, "id": mem_id, "source_type": source_type, "trust_score": trust_score}

    @router.post("/tool-result")
    async def memory_tool_result(body: ToolResultRequest) -> dict:
        """Store a tool call result as OBSERVATION memory.

        P15.1: Mark as tool_verified with high trust.
        """
        repo = await repo_dep()
        if not body.tool_name:
            return {"stored": False, "reason": "no tool_name"}

        import hashlib, json, uuid
        from datetime import datetime, timezone

        content = f"Tool: {body.tool_name}\nResult: {body.result[:2000]}"
        mem_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()
        chk = hashlib.sha256(content.encode()).hexdigest()

        # ── P15.1: tool results are high-trust ──
        source_type = "tool_verified"
        verification_status = "verified"
        trust_data = {
            "source_type": source_type,
            "verification_status": verification_status,
            "confidence_score": 0.9,
            "importance_score": 0.3,
        }
        decision = _trust_scorer.score(trust_data)
        trust_score = decision.trust_score

        async with repo.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memories(
                    id, memory_type, content, content_hash, checksum,
                    importance_score, confidence_score, active_state,
                    valid_from, created_at, updated_at, metadata_json,
                    source_type, verification_status, trust_score
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mem_id, "OBSERVATION", content, chk, chk,
                    0.3, 0.9, "active",
                    now_iso, now_iso, now_iso, json.dumps({
                        "session_id": body.session_id or "default",
                        "source": body.source,
                        "tool_name": body.tool_name,
                    }),
                    source_type, verification_status, trust_score,
                ),
            )
        return {"stored": True, "id": mem_id, "source_type": source_type, "trust_score": trust_score}

    # ── P15.2: Task lifecycle ──

    @router.post("/task/start")
    async def task_start(body: TaskStartRequest, repo: Any = Depends(repo_dep)) -> dict:
        """Start a task — creates a running task entry."""
        import json, traceback, uuid
        from datetime import datetime, timezone

        task_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            import sqlite3
            raw = sqlite3.connect(str(repo.db.db_path))
            raw.execute("PRAGMA foreign_keys=OFF;")
            raw.execute(
                """INSERT OR IGNORE INTO tasks(
                    task_id, session_id, entity_id, task_type, title,
                    status, start_time, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?);""",
                (task_id, body.session_id, body.entity_id, body.task_type, body.title,
                 now_iso, now_iso, now_iso, json.dumps({"source": body.source})),
            )
            raw.commit()
            raw.close()
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

        return {"task_id": task_id, "session_id": body.session_id, "status": "running", "started_at": now_iso}

    @router.post("/task/end")
    async def task_end(body: TaskEndRequest, repo: Any = Depends(repo_dep)) -> dict:
        """End the most recent running task for this session/entity."""
        import json, traceback, uuid
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()

        # Find the most recent running task
        task = await repo.db.fetchone(
            """
            SELECT task_id, session_id, entity_id, task_type, title, start_time
            FROM tasks
            WHERE session_id = ? AND entity_id = ? AND status = 'running'
            ORDER BY start_time DESC
            LIMIT 1;
            """,
            (body.session_id, body.entity_id),
        )

        if not task:
            return {"ended": False, "reason": "no running task found"}

        task_id = task["task_id"]
        started_at = task["start_time"]

        # Compute duration
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            duration = int((end_dt - start_dt).total_seconds())
        except Exception:
            duration = 0

        # Use raw connection to bypass FK constraints on tasks/task_durations
        try:
            import sqlite3
            raw = sqlite3.connect(str(repo.db.db_path))
            raw.execute("PRAGMA foreign_keys=OFF;")
            raw.execute(
                """UPDATE tasks
                SET status = ?, end_time = ?, duration_seconds = ?, updated_at = ?,
                    metadata_json = ?
                WHERE task_id = ?;""",
                (body.status, now_iso, duration, now_iso,
                 json.dumps({"summary": body.summary, "source": body.source}),
                 task_id),
            )
            dur_id = uuid.uuid4().hex
            raw.execute(
                """INSERT INTO task_durations(
                    id, task_id, session_id, entity_id,
                    start_time, end_time, duration_seconds, source, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (dur_id, task_id, body.session_id, body.entity_id,
                 started_at, now_iso, duration, body.source,
                 json.dumps({"summary": body.summary, "task_type": task["task_type"]})),
            )
            raw.commit()
            raw.close()
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

        return {
            "task_id": task_id,
            "session_id": body.session_id,
            "entity_id": body.entity_id,
            "status": body.status,
            "duration_seconds": duration,
            "ended_at": now_iso,
        }

    @router.post("/task/durations")
    async def task_durations(body: TaskDurationsQuery, repo: Any = Depends(repo_dep)) -> dict:
        """Query task durations with optional filters."""
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

        # Aggregate stats
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

        # Per-entity breakdown
        entity_breakdown = await repo.db.fetchall(
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
            "by_entity": [dict(r) for r in entity_breakdown] if entity_breakdown else [],
        }

    @router.post("/entity/timeline")
    async def entity_timeline(body: EntityTimelineQuery, repo: Any = Depends(repo_dep)) -> dict:
        """Get timeline entries for a specific entity."""
        wheres = ["entity_id = ?"]
        params = [body.entity_id]
        if body.since:
            wheres.append("start_time >= ?")
            params.append(body.since)
        if body.until:
            wheres.append("end_time <= ?")
            params.append(body.until)

        where_clause = " AND ".join(wheres)

        rows = await repo.db.fetchall(
            f"""
            SELECT task_id, session_id, task_type, title, start_time, end_time,
                   duration_seconds, status, metadata_json
            FROM tasks
            WHERE {where_clause}
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

    return router