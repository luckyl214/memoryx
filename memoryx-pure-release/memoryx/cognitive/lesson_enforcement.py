from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class LessonMatch:
    lesson_id: str
    memory_id: str | None
    lesson_text: str
    policy_type: str
    severity: float
    recommended_action: str = ""
    match_score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LessonEnforcementDecision:
    decision_id: str
    action_text: str
    decision: str
    policy_level: str
    severity: float
    matched_lessons: list[LessonMatch]
    reason: str
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LessonEnforcementPolicyEngine:
    def __init__(self, *, repository, lesson_policy: Any | None = None) -> None:
        self.repository = repository
        self.lesson_policy = lesson_policy

    async def evaluate_action(self, *, action_text: str, intent: str | None = None, session_id: str | None = None, scope_filter: str | None = None, include_global: bool = True, store: bool = True) -> LessonEnforcementDecision:
        matches = await self._match_lessons(action_text=action_text, intent=intent, session_id=session_id, scope_filter=scope_filter, include_global=include_global)
        decision, policy_level, severity, reason = self._decide(matches)
        result = LessonEnforcementDecision(uuid4().hex, action_text, decision, policy_level, severity, matches, reason, session_id)
        if store:
            await self.persist_decision(result)
        return result

    async def _match_lessons(self, *, action_text: str, intent: str | None, session_id: str | None, scope_filter: str | None, include_global: bool) -> list[LessonMatch]:
        rows: list[dict[str, Any]] = []
        if self.lesson_policy is not None and hasattr(self.lesson_policy, "match"):
            try:
                rows = await self.lesson_policy.match(query=action_text, intent=intent, session_id=session_id, scope_filter=scope_filter, include_global=include_global, limit=5)
            except Exception:
                rows = []
        if not rows:
            where = ["lm.active_state = 'active'", "m.active_state = 'active'"]
            params: list[Any] = []
            if session_id:
                where.append("(m.session_id = ? OR m.scope = 'global')")
                params.append(session_id)
            elif include_global:
                where.append("m.scope = 'global'")
            sql = f"""
                SELECT lm.*, m.content, m.id AS memory_id
                FROM lesson_memories lm
                JOIN memories m ON m.id = lm.memory_id
                WHERE {' AND '.join(where)}
                ORDER BY lm.severity DESC, lm.updated_at DESC
                LIMIT 25;
            """
            db_rows = await self.repository.db.fetchall(sql, tuple(params))
            lowered = action_text.lower()
            for row in db_rows:
                item = dict(row)
                patterns = []
                for key in ("trigger_patterns_json", "prohibited_patterns_json"):
                    try:
                        patterns.extend(json.loads(item.get(key) or "[]"))
                    except Exception:
                        pass
                if any(str(p).lower() in lowered for p in patterns):
                    item["lesson_match_score"] = 0.65
                    rows.append(item)

        matches: list[LessonMatch] = []
        for row in rows:
            matches.append(
                LessonMatch(
                    lesson_id=str(row.get("lesson_id") or row.get("id")),
                    memory_id=row.get("memory_id"),
                    lesson_text=str(row.get("lesson_text") or row.get("content") or ""),
                    policy_type=str(row.get("policy_type") or "warn"),
                    severity=float(row.get("severity") or 0.5),
                    recommended_action=str(row.get("recommended_action") or ""),
                    match_score=float(row.get("lesson_match_score") or 0.0),
                    reasons=list(row.get("lesson_match_reasons") or []),
                )
            )
        return matches

    def _decide(self, matches: list[LessonMatch]) -> tuple[str, str, float, str]:
        if not matches:
            return "allow", "allow", 0.0, "no matching lesson"
        strongest = max(matches, key=lambda m: (m.severity, m.match_score))
        policy = strongest.policy_type.lower()
        action = strongest.recommended_action.lower()
        severity = strongest.severity
        if policy in {"block", "deny"} or "block" in action:
            return "block", "block", severity, "matched blocking lesson"
        if "tool_verification" in action or "verify" in action:
            return "require_tool_verification", "require_tool_verification", severity, "lesson requires external/tool verification"
        if "dry" in action or "dry-run" in action or "dry_run" in action:
            return "require_dry_run", "require_dry_run", severity, "lesson requires dry-run first"
        if "confirm" in action or "confirmation" in action or severity >= 0.85:
            return "require_confirmation", "require_confirmation", severity, "high-severity lesson requires user confirmation"
        if severity >= 0.55 or policy in {"warn", "avoid"}:
            return "warn", "warn", severity, "matched warning lesson"
        return "allow", "info", severity, "matched low-severity informational lesson"

    async def persist_decision(self, decision: LessonEnforcementDecision) -> None:
        primary = decision.matched_lessons[0] if decision.matched_lessons else None
        await self.repository.db.execute(
            """
            INSERT INTO lesson_enforcement_events(id, lesson_id, session_id, action_text, policy_level, decision, reason, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (decision.decision_id, primary.lesson_id if primary else None, decision.session_id, decision.action_text, decision.policy_level, decision.decision, decision.reason, json.dumps(decision.to_dict(), ensure_ascii=False, default=str)),
        )


def render_lesson_enforcement_block(decision: LessonEnforcementDecision) -> str:
    if decision.decision == "allow":
        return ""
    lines = ["## MemoryX Lesson Enforcement", f"Decision: {decision.decision.upper()}", f"Reason: {decision.reason}"]
    for match in decision.matched_lessons[:3]:
        lines.append(f"- Lesson: {match.lesson_text}")
        if match.recommended_action:
            lines.append(f"  Recommended action: {match.recommended_action}")
    if decision.decision in {"require_confirmation", "require_dry_run", "require_tool_verification", "block"}:
        lines.append("Instruction: do not execute the action until the required condition is satisfied.")
    return "\n".join(lines)
