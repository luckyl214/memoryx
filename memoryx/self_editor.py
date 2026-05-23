"""P5: SelfEditor — 自编辑记忆引擎。preview/apply 两阶段。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class SelfEditRequest:
    memory_id: str
    edit_type: str
    changes: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    session_id: str = ""

    def __post_init__(self):
        valid = {"correct", "merge", "forget", "relevance", "enrich"}
        if self.edit_type not in valid:
            raise ValueError(f"edit_type must be one of {valid}, got {self.edit_type}")


@dataclass
class SelfEditPreview:
    memory_id: str
    edit_type: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    message: str = ""


@dataclass
class SelfEditResult:
    memory_id: str
    applied: bool = False
    previews: list[SelfEditPreview] = field(default_factory=list)
    audit_ids: list[str] = field(default_factory=list)
    error: str = ""


class SelfEditor:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def preview(self, request: SelfEditRequest) -> SelfEditPreview:
        memory = await self.repository.get_memory(request.memory_id)
        if not memory:
            return SelfEditPreview(memory_id=request.memory_id, edit_type=request.edit_type, message="memory not found")
        before = dict(memory)
        if request.edit_type == "correct":
            after = {**before, **request.changes, "updated_at": self.repository._now_iso()}
            return SelfEditPreview(memory_id=request.memory_id, edit_type="correct", before=before, after=after, message=f"Will update {len(request.changes)} fields")
        elif request.edit_type == "forget":
            return SelfEditPreview(memory_id=request.memory_id, edit_type="forget", before=before, after={"active_state": "archived", "archived_at": self.repository._now_iso()}, message="Will archive")
        elif request.edit_type == "merge":
            target = request.changes.get("merge_into", "")
            return SelfEditPreview(memory_id=request.memory_id, edit_type="merge", before=before, after={"superseded_by": target, "active_state": "superseded"}, message=f"Will supersede by {target}" if target else "missing merge_into")
        elif request.edit_type == "relevance":
            ns = min(1.0, float(before.get("importance_score", 0.0)) + request.changes.get("delta", 0.1))
            return SelfEditPreview(memory_id=request.memory_id, edit_type="relevance", before=before, after={**before, "importance_score": ns}, message=f"Will adjust importance to {ns:.2f}")
        elif request.edit_type == "enrich":
            extra = json.loads(before.get("metadata_json", "{}"))
            extra.update(request.changes.get("metadata", {}))
            return SelfEditPreview(memory_id=request.memory_id, edit_type="enrich", before=before, after={**before, "metadata_json": json.dumps(extra, ensure_ascii=False)}, message="Will enrich metadata")
        return SelfEditPreview(memory_id=request.memory_id, edit_type=request.edit_type, message="unknown edit_type")

    async def apply(self, request: SelfEditRequest) -> SelfEditResult:
        preview = await self.preview(request)
        if not preview.after or not preview.message:
            return SelfEditResult(memory_id=request.memory_id, applied=False, previews=[preview], error=preview.message or "preview failed")
        if request.edit_type == "correct":
            for k, v in request.changes.items():
                if k in ("id", "created_at"): continue
                await self.repository.db.execute(f"UPDATE memories SET {k}=?, updated_at=datetime('now') WHERE id=?;", (v, request.memory_id))
        elif request.edit_type == "merge":
            t = request.changes.get("merge_into", "")
            if t: await self.repository.supersede_memory(request.memory_id, t)
        elif request.edit_type == "forget":
            await self.repository.rollback_memory(request.memory_id)
        elif request.edit_type == "relevance":
            ns = min(1.0, float(preview.after.get("importance_score", 0.5)) if preview.after else 0.5)
            await self.repository.db.execute("UPDATE memories SET importance_score=?, updated_at=datetime('now') WHERE id=?;", (ns, request.memory_id))
        elif request.edit_type == "enrich":
            m = request.changes.get("metadata", {})
            await self.repository.db.execute("UPDATE memories SET metadata_json=?, updated_at=datetime('now') WHERE id=?;", (json.dumps(m, ensure_ascii=False), request.memory_id))
        await self.repository.append_audit("memories", request.memory_id, f"self_edit_{request.edit_type}", before_json=preview.before, after_json=preview.after)
        return SelfEditResult(memory_id=request.memory_id, applied=True, previews=[preview], audit_ids=[uuid4().hex])
