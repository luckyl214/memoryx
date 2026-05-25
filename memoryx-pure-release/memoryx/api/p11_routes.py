from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from memoryx.cognitive.guarded_generation import CognitiveGuard
from memoryx.cognitive.narrative_reflection import NarrativeReflectionEngine


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
        # Normalize query for FTS5
        tokens = " OR ".join(
            t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in query).split()
            if t
        ) or query
        cursor = conn.execute(
            """
            SELECT id, memory_type, content, importance_score, created_at
            FROM memories
            WHERE active_state = 'active'
              AND (content LIKE ? OR content LIKE ? OR content LIKE ?)
            ORDER BY importance_score DESC, created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", f"%{query[:50]}%", f"%{_first_word(query)}%", limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "memory_type": r[1],
                "content": r[2],
                "score": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


def _first_word(s: str) -> str:
    return s.split(maxsplit=1)[0] if s.strip() else ""


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
        """Build a context block from MemoryX for Hermes pre_llm_call context injection."""
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
        """Auto-store a conversation turn as EPISODIC memory."""
        repo = await repo_dep()
        if not body.user_message and not body.assistant_response:
            return {"stored": False, "reason": "no content"}

        import hashlib, json, uuid
        from datetime import datetime, timezone

        content = f"User: {body.user_message}\nAssistant: {body.assistant_response}"
        mem_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()
        chk = hashlib.sha256(content.encode()).hexdigest()

        async with repo.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memories(id, memory_type, content, content_hash, checksum, importance_score, confidence_score, active_state, valid_from, created_at, updated_at, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mem_id, "EPISODIC", content, chk, chk, 0.4, 0.8, "active", now_iso, now_iso, now_iso, json.dumps({
                    "session_id": body.session_id or "default",
                    "source": body.source,
                })),
            )
        return {"stored": True, "id": mem_id}

    @router.post("/tool-result")
    async def memory_tool_result(body: ToolResultRequest) -> dict:
        """Store a tool call result as OBSERVATION memory."""
        repo = await repo_dep()
        if not body.tool_name:
            return {"stored": False, "reason": "no tool_name"}

        import hashlib, json, uuid
        from datetime import datetime, timezone

        content = f"Tool: {body.tool_name}\nResult: {body.result[:2000]}"
        mem_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()
        chk = hashlib.sha256(content.encode()).hexdigest()

        async with repo.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memories(id, memory_type, content, content_hash, checksum, importance_score, confidence_score, active_state, valid_from, created_at, updated_at, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mem_id, "OBSERVATION", content, chk, chk, 0.3, 0.9, "active", now_iso, now_iso, now_iso, json.dumps({
                    "session_id": body.session_id or "default",
                    "source": body.source,
                    "tool_name": body.tool_name,
                })),
            )
        return {"stored": True, "id": mem_id}

    return router