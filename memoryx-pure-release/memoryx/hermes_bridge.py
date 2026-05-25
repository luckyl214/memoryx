"""Hermes-facing bridge for MemoryX.

This is the product integration layer that makes MemoryX affect agent behavior,
not merely log events. It returns structured blocks for Hermes to inject or use
for action gating.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from memoryx.conversation_log import ConversationLogStore
from memoryx.safety.llm_firewall import LLMFirewall, safety_preamble

try:
    from memoryx.cognitive.guarded_generation import CognitiveGuard
except Exception:  # pragma: no cover
    CognitiveGuard = None  # type: ignore[assignment]

try:
    from memoryx.cognitive.narrative_reflection import NarrativeReflectionEngine
except Exception:  # pragma: no cover
    NarrativeReflectionEngine = None  # type: ignore[assignment]


@dataclass(slots=True)
class HermesBridgeResult:
    event: str
    session_id: str
    context_block: str = ""
    guard_block: str = ""
    decision: str = "allow"
    should_block: bool = False
    requires_user: bool = False
    memories: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HermesMemoryBridge:
    def __init__(
        self,
        *,
        repository,
        query_api=None,
        retrieval_engine=None,
        lesson_policy=None,
        max_context_items: int = 6,
    ) -> None:
        self.repository = repository
        self.query_api = query_api
        self.retrieval_engine = retrieval_engine or getattr(query_api, "retrieval_engine", None)
        self.conversation_log = ConversationLogStore(repository)
        self.llm_firewall = LLMFirewall(repository=repository, strict=True)
        self.cognitive_guard = (
            CognitiveGuard(repository=repository, retrieval_engine=self.retrieval_engine, lesson_policy=lesson_policy)
            if CognitiveGuard is not None
            else None
        )
        self.narrative = NarrativeReflectionEngine(repository=repository) if NarrativeReflectionEngine is not None else None
        self.max_context_items = max_context_items

    async def on_user_message(self, *, session_id: str, content: str, **extra: Any) -> HermesBridgeResult:
        safety = await self.llm_firewall.inspect_user_input(content, session_id=session_id)
        await self.conversation_log.log_turn(session_id=session_id, role="user", content=content)

        memories: list[dict[str, Any]] = []
        if self.query_api is not None and hasattr(self.query_api, "search"):
            try:
                memories = await self.query_api.search(
                    query=content,
                    query_vector=[],
                    limit=self.max_context_items,
                    session_id=session_id,
                    include_global=True,
                    include_lessons=True,
                    explain_scores=True,
                )
            except Exception:
                memories = []

        context_block = self.render_context_block(memories=memories, safety_block=self.llm_firewall.render_policy_block(safety))
        return HermesBridgeResult(
            event="on_user_message",
            session_id=session_id,
            context_block=context_block,
            guard_block=self.llm_firewall.render_policy_block(safety),
            decision=safety.decision,
            should_block=safety.should_block,
            requires_user=safety.requires_user,
            memories=memories,
            metadata={"flags": safety.flags},
        )

    async def on_tool_call(
        self,
        *,
        session_id: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        intent: str | None = None,
        **extra: Any,
    ) -> HermesBridgeResult:
        firewall_decision = await self.llm_firewall.evaluate_tool_call(
            tool_name=tool_name,
            args=args or {},
            session_id=session_id,
        )
        guard_block = self.llm_firewall.render_policy_block(firewall_decision)
        decision = firewall_decision.decision
        should_block = firewall_decision.should_block
        requires_user = firewall_decision.requires_user

        if self.cognitive_guard is not None:
            try:
                action_text = f"{tool_name} {args or {}}"
                action_guard = await self.cognitive_guard.evaluate_action(
                    action_text=action_text,
                    intent=intent,
                    session_id=session_id,
                    store=True,
                )
                if action_guard.guard_block:
                    guard_block = (guard_block + "\n\n" + action_guard.guard_block).strip()
                priority = {
                    "allow": 0,
                    "warn": 1,
                    "require_confirmation": 2,
                    "require_tool_verification": 3,
                    "require_dry_run": 4,
                    "block": 5,
                }
                if priority.get(action_guard.enforcement.decision, 0) > priority.get(decision, 0):
                    decision = action_guard.enforcement.decision
                should_block = should_block or action_guard.should_block
                requires_user = requires_user or action_guard.requires_user
            except Exception:
                pass

        return HermesBridgeResult(
            event="on_tool_call",
            session_id=session_id,
            guard_block=guard_block,
            decision=decision,
            should_block=should_block,
            requires_user=requires_user,
            metadata={"tool_name": tool_name},
        )

    async def on_tool_result(
        self,
        *,
        session_id: str,
        tool_name: str,
        result: Any,
        **extra: Any,
    ) -> HermesBridgeResult:
        text = result if isinstance(result, str) else str(result)
        safety = await self.llm_firewall.inspect_tool_output(text, session_id=session_id)
        return HermesBridgeResult(
            event="on_tool_result",
            session_id=session_id,
            context_block=safety.sanitized_text or "",
            guard_block=self.llm_firewall.render_policy_block(safety),
            decision=safety.decision,
            should_block=safety.should_block,
            requires_user=safety.requires_user,
            metadata={"tool_name": tool_name},
        )

    async def on_assistant_response(self, *, session_id: str, content: str, question: str = "", **extra: Any) -> HermesBridgeResult:
        await self.conversation_log.log_turn(session_id=session_id, role="assistant", content=content)
        safety = await self.llm_firewall.inspect_assistant_output(content, session_id=session_id)

        guard_block = self.llm_firewall.render_policy_block(safety)
        decision = safety.decision
        should_block = safety.should_block

        if self.cognitive_guard is not None:
            try:
                checked = await self.cognitive_guard.verify_answer(
                    question=question,
                    answer=content,
                    session_id=session_id,
                    store=True,
                )
                if checked.guard_block:
                    guard_block = (guard_block + "\n\n" + checked.guard_block).strip()
                should_block = should_block or checked.should_block
                if checked.should_block:
                    decision = "block"
                elif checked.guard_block and decision == "allow":
                    decision = "warn"
            except Exception:
                pass

        return HermesBridgeResult(
            event="on_assistant_response",
            session_id=session_id,
            guard_block=guard_block,
            decision=decision,
            should_block=should_block,
            requires_user=should_block,
            metadata={"flags": safety.flags},
        )

    async def on_session_end(self, *, session_id: str, **extra: Any) -> HermesBridgeResult:
        summary = ""
        if self.narrative is not None:
            try:
                end = datetime.now(timezone.utc)
                start = extra.get("window_start") or end.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                reflection = await self.narrative.generate(
                    window_start=start,
                    window_end=extra.get("window_end") or end.isoformat(),
                    session_id=session_id,
                    reflection_type="session",
                    store=True,
                )
                summary = reflection.summary
            except Exception:
                summary = ""
        return HermesBridgeResult(
            event="on_session_end",
            session_id=session_id,
            context_block=summary,
            metadata={"narrative_summary": bool(summary)},
        )

    def render_context_block(self, *, memories: list[dict[str, Any]], safety_block: str = "") -> str:
        lines = [safety_preamble()]
        if safety_block:
            lines.append(safety_block)
        if memories:
            lines.append("## MemoryX Relevant Context")
            for item in memories[: self.max_context_items]:
                memory_type = item.get("memory_type", "MEMORY")
                score = item.get("final_score", "")
                content = str(item.get("content", "")).strip().replace("\n", " ")
                lines.append(f"- [{memory_type} score={score}] {content[:500]}")
        return "\n".join(lines).strip() + "\n"
