from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from memoryx.llm import SenseNovaLiteClient
from memoryx.services.auto_store_service import AutoStoreService
from memoryx.services.memory_decision import MemoryDecisionService
from memoryx.services.task_service import TaskService


def get_state(request: Request) -> Any:
    if not hasattr(request.app.state, "memoryx"):
        raise HTTPException(503, "memoryx state not configured")
    return request.app.state.memoryx


async def get_repository(request: Request) -> Any:
    state = get_state(request)
    repo = getattr(state, "repository", None)
    if repo is None:
        raise HTTPException(503, "repository not configured")
    return repo


async def get_query_api(request: Request) -> Any:
    state = get_state(request)
    api = getattr(state, "query_api", None)
    if api is None:
        raise HTTPException(503, "query api not configured")
    return api


def build_memory_decision_service() -> MemoryDecisionService:
    try:
        llm_client = SenseNovaLiteClient()
    except Exception:
        llm_client = None
    return MemoryDecisionService(llm_client=llm_client)


async def get_auto_store_service(request: Request) -> AutoStoreService:
    repo = await get_repository(request)
    return AutoStoreService(
        repository=repo,
        decision_service=build_memory_decision_service(),
    )


async def get_task_service(request: Request) -> TaskService:
    repo = await get_repository(request)
    return TaskService(repository=repo)
