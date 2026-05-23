"""P6: Full FastAPI REST application with CRUD, search, feedback, self-edit, consolidation.

Routes:
  GET  /health
  GET  /metrics
  POST /v1/memories
  GET  /v1/memories/{memory_id}
  PATCH /v1/memories/{memory_id}
  DELETE /v1/memories/{memory_id}
  POST /v1/search
  POST /v1/feedback
  POST /v1/self-edit/preview
  POST /v1/self-edit/apply
  POST /v1/consolidation/run
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import verify_api_key
from .rate_limit import EmbeddingConcurrencyGate, SlidingWindowRateLimiter
from .rest_schemas import (
    ConsolidationRequest,
    FeedbackRequest,
    MemoryCreate,
    MemoryResponse,
    MemoryUpdate,
    SearchRequest,
    SelfEditApplyRequest,
    SelfEditPreviewRequest,
)

# ── Globals: wired in from outside ──────────────────────────────

_app_repo = None
_app_api = None
_app_self_editor = None
_app_consolidation = None


def configure(repository, query_api, self_editor=None, consolidation=None):
    """Wire in real dependencies after app startup."""
    global _app_repo, _app_api, _app_self_editor, _app_consolidation
    _app_repo = repository
    _app_api = query_api
    _app_self_editor = self_editor
    _app_consolidation = consolidation


# ── App ─────────────────────────────────────────────────────────

app = FastAPI(title="MemoryX API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rate_limiter = SlidingWindowRateLimiter(max_requests=200, window_seconds=60.0)
embedding_gate = EmbeddingConcurrencyGate(max_concurrent=4)


# ── Health ───────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.1.0"}


@app.get("/health/auth-required")
async def health_auth_required(_key: str | None = Depends(verify_api_key)) -> dict:
    return {"status": "ok", "auth_required": _key is not None}


@app.get("/metrics")
async def metrics(_key: str | None = Depends(verify_api_key)) -> dict:
    if _app_repo is None:
        return {"error": "not configured"}
    count = await _app_repo.db.fetchone("SELECT COUNT(*) AS cnt FROM memories;")
    return {"total_memories": count["cnt"] if count else 0}


# ── CRUD ────────────────────────────────────────────────────────

@app.post("/v1/memories", status_code=201)
async def create_memory(
    body: MemoryCreate,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_repo is None:
        raise HTTPException(500, "not configured")
    from memoryx.storage import MemoryRecord
    record = MemoryRecord(
        id=uuid4().hex,
        memory_type=body.memory_type,
        content=body.content,
        importance_score=body.importance_score,
        confidence_score=body.confidence_score,
        session_id=body.session_id,
        metadata_json=json.dumps(body.metadata, ensure_ascii=False) if body.metadata else "{}",
    )
    mem_id = await _app_repo.store_memory(record)
    return {"id": mem_id}


@app.get("/v1/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_repo is None:
        raise HTTPException(500, "not configured")
    mem = await _app_repo.get_memory(memory_id)
    if not mem:
        raise HTTPException(404, "not found")
    return dict(mem)


@app.patch("/v1/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_repo is None:
        raise HTTPException(500, "not configured")
    mem = await _app_repo.get_memory(memory_id)
    if not mem:
        raise HTTPException(404, "not found")
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items() if v is not None}
    for key, value in updates.items():
        await _app_repo.db.execute(
            f"UPDATE memories SET {key} = ?, updated_at = datetime('now') WHERE id = ?;",
            (value, memory_id),
        )
    return {"id": memory_id, "updated_fields": list(updates.keys())}


@app.delete("/v1/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_repo is None:
        raise HTTPException(500, "not configured")
    await _app_repo.rollback_memory(memory_id)
    return {"id": memory_id, "deleted": True}


# ── Search ──────────────────────────────────────────────────────

@app.post("/v1/search")
async def search(
    body: SearchRequest,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_api is None:
        raise HTTPException(500, "not configured")
    results = await _app_api.search(
        query=body.query,
        query_vector=[],  # FTS-only for REST; vector via embedding_manager on-demand
        limit=body.limit,
        tag_filter=body.tag_filter,
    )
    return {"results": results, "total": len(results)}


# ── Feedback ────────────────────────────────────────────────────

@app.post("/v1/feedback")
async def feedback(
    body: FeedbackRequest,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_api is None:
        raise HTTPException(500, "not configured")
    return await _app_api.feedback(memory_id=body.memory_id, positive=body.positive)


# ── Self-edit ───────────────────────────────────────────────────

@app.post("/v1/self-edit/preview")
async def self_edit_preview(
    body: SelfEditPreviewRequest,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_self_editor is None:
        raise HTTPException(500, "not configured")
    from memoryx.self_editor import SelfEditRequest
    result = await _app_self_editor.preview(SelfEditRequest(
        memory_id=body.memory_id,
        edit_type=body.edit_type,
        changes=body.changes,
        reason=body.reason,
    ))
    return {"preview": result}


@app.post("/v1/self-edit/apply")
async def self_edit_apply(
    body: SelfEditApplyRequest,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_self_editor is None:
        raise HTTPException(500, "not configured")
    from memoryx.self_editor import SelfEditRequest
    result = await _app_self_editor.apply(SelfEditRequest(
        memory_id=body.memory_id,
        edit_type=body.edit_type,
        changes=body.changes,
        reason=body.reason,
    ))
    return {"result": result}


# ── Consolidation ───────────────────────────────────────────────

@app.post("/v1/consolidation/run")
async def consolidation_run(
    body: ConsolidationRequest,
    _key: str | None = Depends(verify_api_key),
) -> dict:
    if _app_consolidation is None:
        raise HTTPException(500, "not configured")
    result = await _app_consolidation.run(limit=body.limit, dry_run=body.dry_run)
    return {"consolidation": result}
