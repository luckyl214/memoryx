"""FastAPI app factory and lifespan wiring for MemoryX.

P12.1 replaces global-only REST state with an app-factory model while keeping a
backward-compatible module-level `app` in memoryx.api.rest_app.

Why this shape fits MemoryX + Hermes:
- MemoryRepository and MemoryQueryAPI are long-lived resources.
- Hermes plugin/runtime may inject pre-built repository/query objects.
- Lifespan guarantees open/close symmetry and avoids hidden global state.
"""

from __future__ import annotations

import inspect
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from memoryx.api.auth import verify_api_key
from memoryx.api.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from memoryx.api.p11_routes import create_p11_router
from memoryx.api.p8_bootstrap import install_p8_observability
from memoryx.api.rate_limit import EmbeddingConcurrencyGate, SlidingWindowRateLimiter
from memoryx.api.rest_schemas import (
    ConsolidationRequest,
    FeedbackRequest,
    MemoryCreate,
    MemoryUpdate,
    SearchRequest,
    SelfEditApplyRequest,
    SelfEditPreviewRequest,
)
from memoryx.observability.metrics import CONTENT_TYPE_LATEST, metrics_response_bytes, record_rest_request


@dataclass(slots=True)
class MemoryXAppState:
    repository: Any | None = None
    query_api: Any | None = None
    self_editor: Any | None = None
    consolidation: Any | None = None
    owns_repository: bool = False
    owns_query_api: bool = False


def _default_db_path() -> Path:
    return Path(os.getenv("MEMORYX_DB_PATH", "./data/memoryx.db"))


async def _build_default_state() -> MemoryXAppState:
    from memoryx.api import MemoryQueryAPI
    from memoryx.storage import MemoryRepository

    db_path = _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    repo = MemoryRepository(db_path)
    await repo.open()
    api = MemoryQueryAPI(repository=repo, vector_store=None)
    return MemoryXAppState(repository=repo, query_api=api, owns_repository=True, owns_query_api=True)


async def _close_state(state: MemoryXAppState) -> None:
    if state.owns_repository and state.repository is not None and hasattr(state.repository, "close"):
        await state.repository.close()


def create_app(
    *,
    repository: Any | None = None,
    query_api: Any | None = None,
    self_editor: Any | None = None,
    consolidation: Any | None = None,
    auto_open: bool = True,
) -> FastAPI:
    initial_state = MemoryXAppState(
        repository=repository,
        query_api=query_api,
        self_editor=self_editor,
        consolidation=consolidation,
        owns_repository=False,
        owns_query_api=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if auto_open and initial_state.repository is None:
            app.state.memoryx = await _build_default_state()
        else:
            app.state.memoryx = initial_state
        try:
            yield
        finally:
            await _close_state(app.state.memoryx)

    app = FastAPI(title="MemoryX API", version="1.1.0", lifespan=lifespan)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    install_p8_observability(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rate_limiter = SlidingWindowRateLimiter(max_requests=200, window_seconds=60.0)
    embedding_gate = EmbeddingConcurrencyGate(max_concurrent=4)

    def state() -> MemoryXAppState:
        if not hasattr(app.state, "memoryx"):
            app.state.memoryx = initial_state
        return app.state.memoryx

    async def ensure_repo():
        repo = state().repository
        if repo is None:
            raise HTTPException(503, "repository not configured")
        return repo

    async def ensure_api():
        api = state().query_api
        if api is None:
            raise HTTPException(503, "query api not configured")
        return api

    async def get_retrieval_engine():
        api = state().query_api
        return getattr(api, "retrieval_engine", None) if api is not None else None

    async def get_lesson_policy():
        engine = await get_retrieval_engine()
        return getattr(engine, "lesson_policy", None) if engine is not None else None

    @app.get("/live")
    async def live() -> dict:
        return {"status": "ok", "live": True, "version": "1.1.0"}

    @app.get("/ready")
    async def ready(_key: str | None = Depends(verify_api_key)) -> dict:
        repo = await ensure_repo()
        checks: dict[str, bool] = {}
        try:
            row = await repo.db.fetchone("SELECT 1 AS ok;", ())
            checks["db"] = bool(row and int(row["ok"]) == 1)
        except Exception:
            checks["db"] = False

        try:
            tables = await repo.db.fetchall("SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table');", ())
            names = {str(r["name"]) for r in tables}
            checks["memories"] = "memories" in names
            checks["memory_versions"] = "memory_versions" in names
            checks["memories_fts"] = "memories_fts" in names
            checks["conversation_logs"] = "conversation_logs" in names
        except Exception:
            checks["memories"] = checks["memory_versions"] = checks["memories_fts"] = checks["conversation_logs"] = False

        if not all(checks.values()):
            raise HTTPException(503, {"ready": False, "checks": checks})
        return {"status": "ok", "ready": True, "checks": checks}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "1.1.0"}

    @app.get("/health/auth-required")
    async def health_auth_required(_key: str | None = Depends(verify_api_key)) -> dict:
        return {"status": "ok", "auth_required": _key is not None}

    @app.get("/metrics")
    async def metrics(_key: str | None = Depends(verify_api_key)) -> Response:
        return Response(content=metrics_response_bytes(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/memories", status_code=201)
    async def create_memory(body: MemoryCreate, _key: str | None = Depends(verify_api_key)) -> dict:
        repo = await ensure_repo()
        from memoryx.storage import MemoryRecord

        record = MemoryRecord(
            id=uuid4().hex,
            memory_type=body.memory_type,
            content=body.content,
            importance_score=body.importance_score,
            confidence_score=body.confidence_score,
            session_id=body.session_id,
            scope=body.scope,
            metadata_json=json.dumps(body.metadata, ensure_ascii=False) if body.metadata else "{}",
        )
        mem_id = await repo.store_memory(record)
        record_rest_request(route="/v1/memories", method="POST", status_code=201)
        return {"id": mem_id}

    @app.get("/v1/memories/{memory_id}")
    async def get_memory(memory_id: str, _key: str | None = Depends(verify_api_key)) -> dict:
        repo = await ensure_repo()
        mem = await repo.get_memory(memory_id)
        if not mem:
            raise HTTPException(404, "not found")
        return dict(mem)

    @app.patch("/v1/memories/{memory_id}")
    async def update_memory(memory_id: str, body: MemoryUpdate, _key: str | None = Depends(verify_api_key)) -> dict:
        repo = await ensure_repo()
        mem = await repo.get_memory(memory_id)
        if not mem:
            raise HTTPException(404, "not found")

        updates = body.model_dump(exclude_none=True)
        if updates:
            if not hasattr(repo, "update_memory_versioned"):
                raise HTTPException(500, "repository.update_memory_versioned is required for PATCH")
            await repo.update_memory_versioned(
                memory_id,
                updates,
                actor="rest_api",
                reason="PATCH /v1/memories/{memory_id}",
            )
        record_rest_request(route="/v1/memories/{memory_id}", method="PATCH", status_code=200)
        return {"id": memory_id, "updated_fields": sorted(updates)}

    @app.delete("/v1/memories/{memory_id}")
    async def delete_memory(memory_id: str, _key: str | None = Depends(verify_api_key)) -> dict:
        repo = await ensure_repo()
        mem = await repo.get_memory(memory_id)
        if not mem:
            raise HTTPException(404, "not found")
        if hasattr(repo, "rollback_memory"):
            await repo.rollback_memory(memory_id)
        elif hasattr(repo, "update_memory_versioned"):
            await repo.update_memory_versioned(
                memory_id,
                {"active_state": "inactive"},
                actor="rest_api",
                reason="DELETE /v1/memories/{memory_id}",
            )
        else:
            raise HTTPException(500, "repository lacks delete/rollback API")
        return {"id": memory_id, "deleted": True}

    @app.post("/v1/search")
    async def search(body: SearchRequest, _key: str | None = Depends(verify_api_key)) -> dict:
        api = await ensure_api()
        kwargs = {
            "query": body.query,
            "query_vector": [],
            "limit": body.limit,
            "tag_filter": body.tag_filter,
            "tag_mode": body.tag_mode,
        }
        sig = inspect.signature(api.search)
        for key, value in {
            "session_id": body.session_id,
            "scope_filter": body.scope_filter,
            "include_global": body.include_global,
            "include_lessons": body.include_lessons,
            "explain_scores": body.explain_scores,
        }.items():
            if key in sig.parameters:
                kwargs[key] = value
        results = await api.search(**kwargs)
        return {"results": results, "total": len(results)}

    @app.post("/v1/feedback")
    async def feedback(body: FeedbackRequest, _key: str | None = Depends(verify_api_key)) -> dict:
        api = await ensure_api()
        sig = inspect.signature(api.feedback)
        kwargs = {"memory_id": body.memory_id, "positive": body.positive}
        for key, value in {
            "reason": body.reason,
            "session_id": body.session_id,
            "dry_run": body.dry_run,
            "propagate": body.propagate,
        }.items():
            if key in sig.parameters:
                kwargs[key] = value
        return await api.feedback(**kwargs)

    @app.post("/v1/self-edit/preview")
    async def self_edit_preview(body: SelfEditPreviewRequest, _key: str | None = Depends(verify_api_key)) -> dict:
        editor = state().self_editor
        if editor is None:
            raise HTTPException(503, "self editor not configured")
        from memoryx.self_editor import SelfEditRequest

        result = await editor.preview(SelfEditRequest(memory_id=body.memory_id, edit_type=body.edit_type, changes=body.changes, reason=body.reason))
        return {"preview": result}

    @app.post("/v1/self-edit/apply")
    async def self_edit_apply(body: SelfEditApplyRequest, _key: str | None = Depends(verify_api_key)) -> dict:
        editor = state().self_editor
        if editor is None:
            raise HTTPException(503, "self editor not configured")
        from memoryx.self_editor import SelfEditRequest

        result = await editor.apply(SelfEditRequest(memory_id=body.memory_id, edit_type=body.edit_type, changes=body.changes, reason=body.reason))
        return {"result": result}

    @app.post("/v1/consolidation/run")
    async def consolidation_run(body: ConsolidationRequest, _key: str | None = Depends(verify_api_key)) -> dict:
        consolidation = state().consolidation
        if consolidation is None:
            raise HTTPException(503, "consolidation not configured")
        result = await consolidation.run(limit=body.limit, dry_run=body.dry_run)
        return {"consolidation": result}

    app.include_router(
        create_p11_router(
            get_repository=ensure_repo,
            get_retrieval_engine=get_retrieval_engine,
            get_lesson_policy=get_lesson_policy,
            prefix="/v1/cognitive",
        )
    )

    app.state.memoryx = initial_state
    return app
