"""Canonical LESSON policy matching for MemoryX."""

from __future__ import annotations

import json
import re
from typing import Any

from memoryx.observability.metrics import lesson_boost_score, lesson_match_total

_WORD_RE = re.compile(r"[\w\-\.]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "") if len(t.strip()) > 1}


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


class LessonPolicyEngine:
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
        tokens = _tokens(query)
        candidate_ids = await self._candidate_lesson_ids(tokens=tokens, intent=intent, limit=max(limit * 8, 40))
        rows = await self._fetch_lessons(
            candidate_ids=candidate_ids,
            session_id=session_id,
            scope_filter=scope_filter,
            include_global=include_global,
            limit=max(limit * 8, 100),
        )

        scored: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            score, reasons = self._score(item, query=query, tokens=tokens, intent=intent)
            if score >= 0.20:
                item["lesson_match_score"] = score
                item["lesson_match_reasons"] = reasons
                scored.append(item)
                lesson_match_total.labels(policy_type=str(item.get("policy_type") or "unknown")).inc()
                lesson_boost_score.observe(score)

        scored.sort(
            key=lambda x: (
                float(x.get("lesson_match_score", 0.0)),
                float(x.get("severity", 0.0)),
                int(x.get("evidence_count", 0) or 0),
            ),
            reverse=True,
        )
        return scored[:limit]

    async def _candidate_lesson_ids(self, *, tokens: set[str], intent: str | None, limit: int) -> list[str] | None:
        if not tokens and not intent:
            return None
        try:
            table = await self.repository.db.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='lesson_triggers';",
                (),
            )
        except Exception:
            return None
        if not table:
            return None

        lookup: list[tuple[str, str]] = []
        if intent:
            lookup.append(("intent", intent.lower()))
        for token in tokens:
            lookup.append(("pattern", token))
            lookup.append(("prohibited", token))

        if not lookup:
            return None

        clauses = []
        params: list[Any] = []
        for typ, trig in lookup[:80]:
            clauses.append("(trigger_type = ? AND trigger = ?)")
            params.extend([typ, trig])

        rows = await self.repository.db.fetchall(
            f"""
            SELECT DISTINCT lesson_id
            FROM lesson_triggers
            WHERE active_state = 'active'
              AND ({' OR '.join(clauses)})
            LIMIT ?;
            """,
            (*params, limit),
        )
        ids = [str(r["lesson_id"]) for r in rows]
        return ids or []

    async def _fetch_lessons(
        self,
        *,
        candidate_ids: list[str] | None,
        session_id: str | None,
        scope_filter: str | None,
        include_global: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        where, params = self._visibility_where(session_id=session_id, scope_filter=scope_filter, include_global=include_global)

        candidate_clause = ""
        candidate_params: list[Any] = []
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ", ".join("?" for _ in candidate_ids)
            candidate_clause = f" AND lm.id IN ({placeholders})"
            candidate_params.extend(candidate_ids)

        return await self.repository.db.fetchall(
            f"""
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
              {candidate_clause}
            ORDER BY lm.severity DESC, lm.updated_at DESC
            LIMIT ?;
            """,
            (*params, *candidate_params, limit),
        )

    def _score(self, lesson: dict[str, Any], *, query: str, tokens: set[str], intent: str | None) -> tuple[float, list[str]]:
        q = query.lower()
        reasons: list[str] = []
        trigger_intents = {x.lower() for x in _json_list(lesson.get("trigger_intents_json"))}
        trigger_patterns = {x.lower() for x in _json_list(lesson.get("trigger_patterns_json"))}
        prohibited_patterns = {x.lower() for x in _json_list(lesson.get("prohibited_patterns_json"))}

        score = 0.0
        if intent and intent.lower() in trigger_intents:
            score += 0.30
            reasons.append(f"intent:{intent}")

        for pattern in sorted(trigger_patterns):
            if pattern and (pattern in tokens or pattern in q):
                score += 0.22
                reasons.append(f"trigger:{pattern}")

        for pattern in sorted(prohibited_patterns):
            if pattern and (pattern in tokens or pattern in q):
                score += 0.38
                reasons.append(f"prohibited:{pattern}")

        lesson_tokens = _tokens(str(lesson.get("lesson_text") or lesson.get("content") or "").lower())
        if tokens and lesson_tokens:
            overlap = len(tokens & lesson_tokens) / max(1, min(len(tokens), len(lesson_tokens)))
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


async def sync_lesson_triggers(repository, lesson_id: str) -> int:
    row = await repository.db.fetchone("SELECT * FROM lesson_memories WHERE id = ?;", (lesson_id,))
    if not row:
        return 0
    item = dict(row)
    triggers: list[tuple[str, str]] = []
    for intent in _json_list(item.get("trigger_intents_json")):
        triggers.append(("intent", intent.lower()))
    for pattern in _json_list(item.get("trigger_patterns_json")):
        triggers.append(("pattern", pattern.lower()))
    for pattern in _json_list(item.get("prohibited_patterns_json")):
        triggers.append(("prohibited", pattern.lower()))

    await repository.db.execute("DELETE FROM lesson_triggers WHERE lesson_id = ?;", (lesson_id,))
    inserted = 0
    for trigger_type, trigger in sorted(set(triggers)):
        if not trigger:
            continue
        await repository.db.execute(
            """
            INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type, active_state)
            VALUES (?, ?, ?, 'active');
            """,
            (lesson_id, trigger, trigger_type),
        )
        inserted += 1
    return inserted
