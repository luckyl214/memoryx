from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memoryx.cognitive.guarded_generation import CognitiveGuard
from memoryx.cognitive.narrative_reflection import NarrativeReflectionEngine


class VerifyAnswerRequest(BaseModel):
    question: str
    answer: str
    session_id: str | None = None
    store: bool = True


class EvaluateActionRequest(BaseModel):
    action_text: str
    intent: str | None = None
    session_id: str | None = None
    store: bool = True


class NarrativeRequest(BaseModel):
    window_start: str
    window_end: str
    session_id: str | None = None
    entity_id: str | None = None
    reflection_type: str = "periodic"
    store: bool = True


def create_p11_router(*, repository, retrieval_engine=None, lesson_policy=None) -> APIRouter:
    router = APIRouter(prefix="/v1/cognitive", tags=["cognitive"])
    guard = CognitiveGuard(repository=repository, retrieval_engine=retrieval_engine, lesson_policy=lesson_policy)
    narrative = NarrativeReflectionEngine(repository=repository)

    @router.post("/verify-answer")
    async def verify_answer(body: VerifyAnswerRequest) -> dict:
        result = await guard.verify_answer(question=body.question, answer=body.answer, session_id=body.session_id, store=body.store)
        return {"should_block": result.should_block, "guard_block": result.guard_block, "verification": result.verification.to_dict()}

    @router.post("/evaluate-action")
    async def evaluate_action(body: EvaluateActionRequest) -> dict:
        result = await guard.evaluate_action(action_text=body.action_text, intent=body.intent, session_id=body.session_id, store=body.store)
        return {"should_block": result.should_block, "requires_user": result.requires_user, "guard_block": result.guard_block, "enforcement": result.enforcement.to_dict()}

    @router.post("/narrative-reflection")
    async def narrative_reflection(body: NarrativeRequest) -> dict:
        if body.window_start >= body.window_end:
            raise HTTPException(400, "window_start must be earlier than window_end")
        result = await narrative.generate(window_start=body.window_start, window_end=body.window_end, session_id=body.session_id, entity_id=body.entity_id, reflection_type=body.reflection_type, store=body.store)
        return result.to_dict()

    return router
