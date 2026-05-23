"""FastAPI REST application for MemoryX.

Hardening:
- Uniform error responses.
- /live and /ready probes.
- PATCH writes through update_memory_versioned().
- /metrics emits Prometheus format when prometheus-client is available.
"""

from __future__ import annotations

import inspect
import json
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from memoryx.observability.metrics import CONTENT_TYPE_LATEST, metrics_response_bytes, rest_requests_total

from .auth import verify_api_key
from .errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from .rate_limit import EmbeddingConcurrencyGate, SlidingWindowRateLimiter
from .rest_schemas import (
    ConsolidationRequest,
    FeedbackRequest,
    MemoryCreate,
    MemoryUpdate,
    SearchRequest,
    SelfEditApplyRequest,
    SelfEditPreviewRequest,
)

_app_repo = None
_app_api = None
_app_self_editor = None
_app_consolidation = None


def configure(repository, query_api, self_editor=None, consolidation=None):
    global _app_repo, _app_api, _app_self_editor, _app_consolidation
    _app_repo = repository
    _app_api = query_api
    _app_self_editor = self_editor
    _app_consolidation = consolidation


app = FastAPI(title="MemoryX API", version="1.1.0")

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rate_limiter = SlidingWindowRateLimiter(max_requests=200, window_seconds=60.0)
embedding_gate = EmbeddingConcurrencyGate(max_concurrent=4)


def _record_rest(route: str, status_code: int) -> None:
    rest_requests_total.labels(route=route, status_code=str(status_code)).inc()


async def _ensure_repo():
    if _app_repo is None:
        raise HTTPException(503, "repository not configured")
    return _app_repo


async def _ensure_api():
    if _app_api is None:
        raise HTTPException(503, "query api not configured")
    return _app_api


@app.get("/live")
async def live() -> dict:
    return {"status": "ok", "live": True, "version": "1.1.0"}


@app.get("/ready")
async def ready(_key: str | None = Depends(verify_api_key)) -> dict:
    if _app_repo is None:
        raise HTTPException(503, "repository not configured")

    checks: dict[str, bool] = {}
    try:
        row = await _app_repo.db.fetchone("SELECT 1 AS ok;", ())
        checks["db"] = bool(row and int(row["ok"]) == 1)
    except Exception:
        checks["db"] = False

    try:
        tables = await _app_repo.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table');",
            (),
        )
        names = {str(r["name"]) for r in tables}
        checks["memories"] = "memories" in names
        checks["memory_versions"] = "memory_versions" in names
        checks["memories_fts"] = "memories_fts" in names
    except Exception:
        checks["memories"] = checks["memory_versions"] = checks["memories_fts"] = False

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
    repo = await _ensure_repo()
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
    _record_rest("/v1/memories", 201)
    return {"id": mem_id}


@app.get("/v1/memories/{memory_id}")
async def get_memory(memory_id: str, _key: str | None = Depends(verify_api_key)) -> dict:
    repo = await _ensure_repo()
    mem = await repo.get_memory(memory_id)
    if not mem:
        raise HTTPException(404, "not found")
    return dict(mem)


@app.patch("/v1/memories/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdate, _key: str | None = Depends(verify_api_key)) -> dict:
    repo = await _ensure_repo()
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
    _record_rest("/v1/memories/{memory_id}", 200)
    return {"id": memory_id, "updated_fields": sorted(updates)}


@app.delete("/v1/memories/{memory_id}")
async def delete_memory(memory_id: str, _key: str | None = Depends(verify_api_key)) -> dict:
    repo = await _ensure_repo()
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
    api = await _ensure_api()
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
    api = await _ensure_api()
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
    if _app_self_editor is None:
        raise HTTPException(503, "self editor not configured")
    from memoryx.self_editor import SelfEditRequest

    result = await _app_self_editor.preview(
        SelfEditRequest(memory_id=body.memory_id, edit_type=body.edit_type, changes=body.changes, reason=body.reason)
    )
    return {"preview": result}


@app.post("/v1/self-edit/apply")
async def self_edit_apply(body: SelfEditApplyRequest, _key: str | None = Depends(verify_api_key)) -> dict:
    if _app_self_editor is None:
        raise HTTPException(503, "self editor not configured")
    from memoryx.self_editor import SelfEditRequest

    result = await _app_self_editor.apply(
        SelfEditRequest(memory_id=body.memory_id, edit_type=body.edit_type, changes=body.changes, reason=body.reason)
    )
    return {"result": result}


@app.post("/v1/consolidation/run")
async def consolidation_run(body: ConsolidationRequest, _key: str | None = Depends(verify_api_key)) -> dict:
    if _app_consolidation is None:
        raise HTTPException(503, "consolidation not configured")
    result = await _app_consolidation.run(limit=body.limit, dry_run=body.dry_run)
    return {"consolidation": result}
