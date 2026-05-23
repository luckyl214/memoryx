from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .claim_guard import ClaimVerificationReport, ClaimVerifier, render_claim_guard_block
from .lesson_enforcement import LessonEnforcementDecision, LessonEnforcementPolicyEngine, render_lesson_enforcement_block


@dataclass(slots=True)
class GuardedAnswer:
    answer: str
    verification: ClaimVerificationReport
    guard_block: str
    should_block: bool


@dataclass(slots=True)
class GuardedAction:
    action_text: str
    enforcement: LessonEnforcementDecision
    guard_block: str
    should_block: bool
    requires_user: bool


class CognitiveGuard:
    def __init__(self, *, repository, retrieval_engine: Any | None = None, lesson_policy: Any | None = None) -> None:
        self.claim_verifier = ClaimVerifier(repository=repository, retrieval_engine=retrieval_engine)
        self.lesson_enforcer = LessonEnforcementPolicyEngine(repository=repository, lesson_policy=lesson_policy)

    async def verify_answer(self, *, question: str, answer: str, session_id: str | None = None, store: bool = True) -> GuardedAnswer:
        report = await self.claim_verifier.verify_answer(question=question, answer=answer, session_id=session_id, store=store)
        block = render_claim_guard_block(report)
        return GuardedAnswer(answer, report, block, report.action == "block")

    async def evaluate_action(self, *, action_text: str, intent: str | None = None, session_id: str | None = None, store: bool = True) -> GuardedAction:
        decision = await self.lesson_enforcer.evaluate_action(action_text=action_text, intent=intent, session_id=session_id, store=store)
        block = render_lesson_enforcement_block(decision)
        return GuardedAction(action_text, decision, block, decision.decision == "block", decision.decision in {"require_confirmation", "require_dry_run", "require_tool_verification", "block"})
