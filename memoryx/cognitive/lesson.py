from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from memoryx.storage import MemoryRecord

from .models import LessonMatch, LessonSpec

_WORD_RE = re.compile(r"[\w\-\.]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "") if len(t.strip()) > 1}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class LessonAbstractionEngine:
    """Turns repeated negative evidence into executable LESSON memories.

    This is deterministic and local-first. If you later inject an LLM client,
    use it only to polish wording, never to invent evidence.
    """

    def __init__(self, *, repository, llm_client=None) -> None:
        self.repository = repository
        self.llm_client = llm_client

    async def maybe_create_lesson(
        self,
        *,
        root_memory_id: str,
        evidence_memory_ids: list[str],
        trigger_context: dict[str, Any] | None = None,
        dry_run: bool = False,
        min_evidence: int = 2,
    ) -> str | None:
        unique_evidence = list(dict.fromkeys([root_memory_id, *evidence_memory_ids]))
        if len(unique_evidence) < min_evidence:
            return None
        root = await self.repository.get_memory(root_memory_id)
        if not root:
            return None
        contents: list[str] = []
        for mid in unique_evidence[:8]:
            mem = await self.repository.get_memory(mid)
            if mem and mem.get("content"):
                contents.append(str(mem["content"]))
        spec = self._build_spec(
            root=root,
            contents=contents,
            context=trigger_context or {},
            evidence_ids=unique_evidence,
        )
        if dry_run:
            return f"DRY_RUN:{spec.lesson_text}"
        return await self.create_lesson(spec)

    async def create_lesson(self, spec: LessonSpec) -> str:
        lesson_memory_id = uuid4().hex
        metadata = {
            "scope": "global",
            "tags": ["lesson", "feedback", spec.policy_type],
            "entities": list(spec.trigger_patterns[:8]),
            "lesson": {
                "policy_type": spec.policy_type,
                "severity": spec.severity,
                "recommended_action": spec.recommended_action,
            },
            **spec.metadata,
        }
        record = MemoryRecord(
            id=lesson_memory_id,
            memory_type="LESSON",
            content=spec.lesson_text,
            content_summary=spec.lesson_text[:240],
            importance_score=max(0.8, min(1.0, spec.severity)),
            confidence_score=spec.confidence_score,
            metadata_json=_json(metadata),
        )
        await self.repository.store_memory(record)
        lesson_id = uuid4().hex
        await self.repository.db.execute(
            """
            INSERT INTO lesson_memories(
                id, memory_id, lesson_text, policy_type, severity,
                trigger_intents_json, trigger_patterns_json, prohibited_patterns_json,
                recommended_action, evidence_count, confidence_score,
                active_state, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?);
            """,
            (
                lesson_id,
                lesson_memory_id,
                spec.lesson_text,
                spec.policy_type,
                float(spec.severity),
                _json(spec.trigger_intents),
                _json(spec.trigger_patterns),
                _json(spec.prohibited_patterns),
                spec.recommended_action,
                len(spec.evidence_memory_ids),
                float(spec.confidence_score),
                _json(spec.metadata),
            ),
        )
        for evidence_id in spec.evidence_memory_ids:
            await self.repository.db.execute(
                """
                INSERT OR IGNORE INTO lesson_evidence(lesson_id, evidence_memory_id, evidence_type, weight)
                VALUES (?, ?, 'feedback', 1.0);
                """,
                (lesson_id, evidence_id),
            )
        await self.repository.append_audit(
            entity_type="lesson_memories",
            entity_id=lesson_id,
            action="lesson_created",
            after_json={"memory_id": lesson_memory_id, "evidence_count": len(spec.evidence_memory_ids)},
        )
        return lesson_memory_id

    def _build_spec(
        self,
        *,
        root: dict[str, Any],
        contents: list[str],
        context: dict[str, Any],
        evidence_ids: list[str],
    ) -> LessonSpec:
        text = "\n".join(contents)
        toks = _tokens(text)
        trigger_patterns = sorted(t for t in toks if t.startswith("--") or t in {
            "deploy", "deployment", "production", "prod", "force", "rollback",
            "delete", "drop", "truncate", "secret", "token", "api", "timeout",
            "sqlite", "queue", "async", "debug", "bug", "error", "param", "argument",
        })[:16]
        lowered = text.lower()
        trigger_intents: list[str] = []
        if any(k in lowered for k in ("deploy", "production", "rollback")):
            trigger_intents.append("deployment")
        if any(k in lowered for k in ("bug", "debug", "timeout", "error")):
            trigger_intents.append("debugging")
        if any(k in lowered for k in ("api", "param", "argument", "code")):
            trigger_intents.append("coding")
        if not trigger_intents:
            trigger_intents = [str(context.get("intent") or "general")]

        prohibited = [t for t in trigger_patterns if t.startswith("--") or t in {"force", "drop", "truncate"}]
        root_content = str(root.get("content") or "").strip()
        reason = str(context.get("reason") or "negative feedback").strip()
        lesson_text = (
            "根据过往负反馈与相似错误证据，处理相似任务时不要直接重复该做法："
            f"{root_content[:240]}。触发原因：{reason}。"
        )
        if prohibited:
            lesson_text += " 尤其需要二次确认或避免使用：" + ", ".join(prohibited[:8]) + "。"
        severity = min(1.0, 0.70 + 0.05 * max(0, len(evidence_ids) - 2))
        return LessonSpec(
            lesson_text=lesson_text,
            policy_type="avoid" if prohibited else "warn",
            severity=severity,
            trigger_intents=trigger_intents,
            trigger_patterns=trigger_patterns,
            prohibited_patterns=prohibited,
            recommended_action="retrieve_related_lesson_and_ask_for_confirmation_before_acting",
            evidence_memory_ids=evidence_ids,
            confidence_score=min(0.95, 0.55 + 0.10 * len(evidence_ids)),
            metadata={"root_memory_id": root.get("id"), "generated_by": "LessonAbstractionEngine"},
        )


class LessonPolicyEngine:
    """Matches active LESSON memories against the current query/task context."""

    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def match(
        self,
        *,
        query: str,
        context: dict[str, Any] | None = None,
        intent: str | None = None,
        limit: int = 5,
    ) -> list[LessonMatch]:
        q_tokens = _tokens(query)
        ctx = context or {}
        intent_value = intent or str(ctx.get("intent") or "")
        rows = await self.repository.db.fetchall(
            """
            SELECT * FROM lesson_memories
            WHERE active_state = 'active'
            ORDER BY severity DESC, updated_at DESC
            LIMIT 100;
            """
        )
        matches: list[LessonMatch] = []
        for row in rows:
            item = dict(row)
            patterns = {str(x).lower() for x in _loads(item.get("trigger_patterns_json"), [])}
            intents = {str(x).lower() for x in _loads(item.get("trigger_intents_json"), [])}
            text_tokens = _tokens(str(item.get("lesson_text") or ""))
            overlap = 0.0
            if q_tokens:
                overlap = len(q_tokens & (patterns | text_tokens)) / max(len(q_tokens), 1)
            intent_bonus = 0.25 if intent_value and intent_value.lower() in intents else 0.0
            severity = float(item.get("severity") or 0.0)
            confidence = float(item.get("confidence_score") or 0.0)
            score = overlap + intent_bonus + 0.25 * severity + 0.15 * confidence
            if score <= 0.25:
                continue
            matches.append(LessonMatch(
                lesson_id=str(item["id"]),
                memory_id=str(item["memory_id"]),
                lesson_text=str(item["lesson_text"]),
                policy_type=str(item["policy_type"]),
                severity=severity,
                confidence_score=confidence,
                match_score=score,
                recommended_action=str(item.get("recommended_action") or ""),
                evidence_count=int(item.get("evidence_count") or 0),
            ))
        matches.sort(key=lambda x: x.match_score, reverse=True)
        return matches[:limit]

    async def render_instructions(self, lessons: list[LessonMatch]) -> str:
        if not lessons:
            return ""
        lines = ["\n## Relevant operational lessons"]
        for item in lessons:
            lines.append(
                f"- [{item.policy_type.upper()}] {item.lesson_text} "
                f"(severity={item.severity:.2f}, confidence={item.confidence_score:.2f}, evidence={item.evidence_count})"
            )
            if item.recommended_action:
                lines.append(f"  Recommended action: {item.recommended_action}")
        return "\n".join(lines) + "\n"
