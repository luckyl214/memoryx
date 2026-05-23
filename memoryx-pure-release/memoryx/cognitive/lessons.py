"""Cognitive lessons module — LessonPolicyEngine for retrieval matching."""
from __future__ import annotations

import json
import re
from typing import Any


def _json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        return []
    return []


def _normalize_text(value: str) -> str:
    return str(value or "").lower().strip()


class LessonPolicyEngine:
    """Match executable LESSON memories against a retrieval query."""

    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def match(
        self,
        *,
        query: str,
        intent: str | None = None,
        session_id: str | None = None,
        scope_filter: str | None = None,
        include_global: bool = True,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        where, params = self._visibility_where(
            session_id=session_id,
            scope_filter=scope_filter,
            include_global=include_global,
        )

        sql = f"""
            SELECT
                m.id AS memory_id,
                m.content AS content,
                m.memory_type AS memory_type,
                m.importance_score AS importance_score,
                m.confidence_score AS confidence_score,
                m.scope AS scope,
                m.session_id AS session_id,
                lm.id AS lesson_id,
                lm.lesson_text AS lesson_text,
                lm.policy_type AS policy_type,
                lm.severity AS severity,
                lm.trigger_intents_json AS trigger_intents_json,
                lm.trigger_patterns_json AS trigger_patterns_json,
                lm.prohibited_patterns_json AS prohibited_patterns_json,
                lm.recommended_action AS recommended_action,
                lm.evidence_count AS evidence_count
            FROM lesson_memories lm
            JOIN memories m ON m.id = lm.memory_id
            WHERE lm.active_state = 'active'
              AND m.active_state = 'active'
              AND {where}
            ORDER BY lm.severity DESC, lm.updated_at DESC
            LIMIT 100;
        """

        rows = await self.repository.db.fetchall(sql, params)
        scored: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            score, reasons = self._score_lesson(item, query=query, intent=intent)
            if score >= 0.20:
                item["lesson_match_score"] = score
                item["lesson_match_reasons"] = reasons
                scored.append(item)

        scored.sort(
            key=lambda x: (
                float(x.get("lesson_match_score", 0.0)),
                float(x.get("severity", 0.0)),
                int(x.get("evidence_count", 0) or 0),
            ),
            reverse=True,
        )
        return scored[:limit]

    def _score_lesson(
        self,
        lesson: dict[str, Any],
        *,
        query: str,
        intent: str | None = None,
    ) -> tuple[float, list[str]]:
        q = _normalize_text(query)
        reasons: list[str] = []

        trigger_intents = _json_list(lesson.get("trigger_intents_json"))
        trigger_patterns = _json_list(lesson.get("trigger_patterns_json"))
        prohibited_patterns = _json_list(lesson.get("prohibited_patterns_json"))

        score = 0.0
        if intent and intent in trigger_intents:
            score += 0.30
            reasons.append(f"intent:{intent}")

        for pat in trigger_patterns:
            p = _normalize_text(pat)
            if p and p in q:
                score += 0.22
                reasons.append(f"trigger:{pat}")

        for pat in prohibited_patterns:
            p = _normalize_text(pat)
            if p and p in q:
                score += 0.38
                reasons.append(f"prohibited:{pat}")

        lesson_text = _normalize_text(lesson.get("lesson_text") or lesson.get("content") or "")
        q_tokens = set(re.findall(r"[\w\-]+", q))
        l_tokens = set(re.findall(r"[\w\-]+", lesson_text))
        if q_tokens and l_tokens:
            overlap = len(q_tokens & l_tokens) / max(1, min(len(q_tokens), len(l_tokens)))
            if overlap >= 0.25:
                score += min(0.20, overlap * 0.20)
                reasons.append(f"token_overlap:{overlap:.2f}")

        severity = float(lesson.get("severity") or 0.0)
        confidence = float(lesson.get("confidence_score") or 0.5)
        evidence = min(1.0, float(lesson.get("evidence_count") or 0) / 3.0)

        score += 0.10 * severity
        score += 0.05 * confidence
        score += 0.05 * evidence

        return min(1.0, score), reasons

    def _visibility_where(
        self,
        *,
        session_id: str | None,
        scope_filter: str | None,
        include_global: bool,
    ) -> tuple[str, list[Any]]:
        visible: list[str] = []
        params: list[Any] = []

        if session_id:
            visible.append("m.session_id = ?")
            params.append(session_id)

        if scope_filter:
            visible.append("m.scope = ?")
            params.append(scope_filter)

        if include_global:
            visible.append("m.scope = 'global'")

        if not visible:
            return "1 = 1", []

        return "(" + " OR ".join(visible) + ")", params
