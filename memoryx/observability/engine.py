from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import cast, Any

from memoryx.context import ContextBundle


class MemoryObservabilityEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def memory_access_logs(self, *, memory_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.repository is None:
            return []
        rows = await self.repository.db.fetchall(
            "SELECT * FROM memory_access_logs WHERE memory_id = ? ORDER BY created_at DESC LIMIT ?;",
            (memory_id, limit),
        )
        return [dict(row) for row in rows]

    async def audit_logs(self, *, subject_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """subject_id maps to entity_id in P0 audit_logs schema."""
        if self.repository is None:
            return []
        rows = await self.repository.db.fetchall(
            "SELECT * FROM audit_logs WHERE entity_id = ? ORDER BY created_at ASC LIMIT ?;",
            (subject_id, limit),
        )
        return [dict(row) for row in rows]

    async def memory_lineage(self, *, memory_id: str) -> dict[str, Any]:
        if self.repository is None:
            return {"memory_id": memory_id, "versions": [], "audits": []}
        version_rows = await self.repository.db.fetchall(
            "SELECT * FROM memory_versions WHERE memory_id = ? ORDER BY version ASC;",
            (memory_id,),
        )
        audits = await self.audit_logs(subject_id=memory_id, limit=200)
        return {
            "memory_id": memory_id,
            "versions": [dict(row) for row in version_rows],
            "audits": audits,
        }

    def retrieval_trace(self, *, query: str, route: str, intent: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        top_score = max((float(item.get("final_score", 0.0)) for item in results), default=0.0)
        return {
            "query": query,
            "route": route,
            "intent": intent,
            "result_count": len(results),
            "top_score": top_score,
            "results": results,
        }

    def context_trace(self, bundle: ContextBundle) -> dict[str, Any]:
        sections = {name: len(items) for name, items in bundle.sections.items()}
        return {
            "rendered_chars": len(bundle.rendered),
            "token_count": bundle.token_count,
            "truncated": bundle.truncated,
            "used_summary_fallback": bundle.used_summary_fallback,
            "sections": sections,
        }

    def scoring_trace(self, result: Any) -> dict[str, Any]:
        if is_dataclass(result) and not isinstance(result, type):
            payload = asdict(cast(Any, result))
        elif not isinstance(result, type) and hasattr(result, "model_dump"):
            payload = result.model_dump()
        elif isinstance(result, dict):
            payload = dict(result)
        else:
            payload = {"value": repr(result)}
        return payload
