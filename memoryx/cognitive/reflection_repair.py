from __future__ import annotations

import json
from dataclasses import asdict
from uuid import uuid4

from memoryx.self_editor import SelfEditRequest

from .models import ReflectionFinding


class ReflectionRepairPlanner:
    """Converts structured reflection findings into dry-run SelfEditRequest plans."""

    def __init__(self, *, repository, self_editor) -> None:
        self.repository = repository
        self.self_editor = self_editor

    async def plan(self, findings: list[ReflectionFinding], *, dry_run: bool = True) -> list[SelfEditRequest]:
        requests: list[SelfEditRequest] = []
        for finding in findings:
            if finding.confidence_score < 0.55 or not finding.evidence_memory_ids:
                continue
            primary = finding.evidence_memory_ids[0]
            action = finding.suggested_action.lower().strip()
            if action == "merge" and len(finding.evidence_memory_ids) >= 2:
                requests.append(SelfEditRequest(primary, "merge", {"merge_into": finding.evidence_memory_ids[1]}, finding.summary, finding.session_id or ""))
            elif action in {"archive", "forget"}:
                requests.append(SelfEditRequest(primary, "forget", {}, finding.summary, finding.session_id or ""))
            elif action in {"correct", "update"}:
                requests.append(SelfEditRequest(primary, "correct", finding.changes, finding.summary, finding.session_id or ""))
            elif action in {"lower_confidence", "relevance"}:
                requests.append(SelfEditRequest(primary, "relevance", {"delta": float(finding.changes.get("delta", -0.1))}, finding.summary, finding.session_id or ""))
        return requests

    async def preview_and_persist(
        self,
        requests: list[SelfEditRequest],
        *,
        source_reflection_id: str | None = None,
        session_id: str | None = None,
    ) -> list[str]:
        plan_ids: list[str] = []
        for request in requests:
            preview = await self.self_editor.preview(request)
            plan_id = uuid4().hex
            await self.repository.db.execute(
                """
                INSERT INTO self_edit_plans(id, source_reflection_id, session_id, status, request_json, preview_json)
                VALUES (?, ?, ?, 'preview', ?, ?);
                """,
                (
                    plan_id,
                    source_reflection_id,
                    session_id or request.session_id or None,
                    json.dumps(asdict(request), ensure_ascii=False, sort_keys=True),
                    json.dumps(asdict(preview), ensure_ascii=False, sort_keys=True, default=str),
                ),
            )
            plan_ids.append(plan_id)
        return plan_ids
