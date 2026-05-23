from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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


async def _resolve(value_or_factory):
    if callable(value_or_factory):
        value = value_or_factory()
        if hasattr(value, "__await__"):
            return await value
        return value
    return value_or_factory


def create_p11_router(
    *,
    repository=None,
    retrieval_engine=None,
    lesson_policy=None,
    get_repository: Callable[[], Any | Awaitable[Any]] | None = None,
    get_retrieval_engine: Callable[[], Any | Awaitable[Any]] | None = None,
    get_lesson_policy: Callable[[], Any | Awaitable[Any]] | None = None,
    prefix: str = "/v1/cognitive",
) -> APIRouter:
    """Create P11 routes with lazy dependency resolution.

    This avoids capturing repository=None during import-time app creation and
    makes FastAPI lifespan/app-factory wiring safe.
    """

    router = APIRouter(prefix=prefix, tags=["cognitive"])

    async def repo_dep():
        repo = await _resolve(get_repository) if get_repository is not None else repository
        if repo is None:
            raise HTTPException(503, "repository not configured")
        return repo

    async def retrieval_dep():
        if get_retrieval_engine is not None:
            return await _resolve(get_retrieval_engine)
        return retrieval_engine

    async def lesson_dep():
        if get_lesson_policy is not None:
            return await _resolve(get_lesson_policy)
        return lesson_policy

    @router.post("/verify-answer")
    async def verify_answer(body: VerifyAnswerRequest) -> dict:
        repo = await repo_dep()
        guard = CognitiveGuard(
            repository=repo,
            retrieval_engine=await retrieval_dep(),
            lesson_policy=await lesson_dep(),
        )
        result = await guard.verify_answer(
            question=body.question,
            answer=body.answer,
            session_id=body.session_id,
            store=body.store,
        )
        return {
            "should_block": result.should_block,
            "guard_block": result.guard_block,
            "verification": result.verification.to_dict(),
        }

    @router.post("/evaluate-action")
    async def evaluate_action(body: EvaluateActionRequest) -> dict:
        repo = await repo_dep()
        guard = CognitiveGuard(
            repository=repo,
            retrieval_engine=await retrieval_dep(),
            lesson_policy=await lesson_dep(),
        )
        result = await guard.evaluate_action(
            action_text=body.action_text,
            intent=body.intent,
            session_id=body.session_id,
            store=body.store,
        )
        return {
            "should_block": result.should_block,
            "requires_user": result.requires_user,
            "guard_block": result.guard_block,
            "enforcement": result.enforcement.to_dict(),
        }

    @router.post("/narrative-reflection")
    async def narrative_reflection(body: NarrativeRequest) -> dict:
        if body.window_start >= body.window_end:
            raise HTTPException(400, "window_start must be earlier than window_end")
        repo = await repo_dep()
        narrative = NarrativeReflectionEngine(repository=repo)
        result = await narrative.generate(
            window_start=body.window_start,
            window_end=body.window_end,
            session_id=body.session_id,
            entity_id=body.entity_id,
            reflection_type=body.reflection_type,
            store=body.store,
        )
        return result.to_dict()

    return router
