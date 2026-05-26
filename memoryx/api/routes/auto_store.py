from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from memoryx.services.auto_store_service import AutoStoreService
from memoryx.api.dependencies import get_auto_store_service


router = APIRouter(prefix="/v1/cognitive", tags=["cognitive-auto-store"])


class MemoryAutoStoreRequest(BaseModel):
    session_id: str = "default"
    user_message: str = ""
    assistant_response: str = ""
    source: str = "hermes.post_llm_call"


class ToolResultRequest(BaseModel):
    session_id: str = "default"
    tool_name: str = ""
    result: str = ""
    source: str = "hermes.post_tool_call"


@router.post("/auto-store-v2")
async def memory_auto_store_v2(
    body: MemoryAutoStoreRequest,
    service: AutoStoreService = Depends(get_auto_store_service),
) -> dict:
    result = await service.store_conversation_turn(
        session_id=body.session_id,
        user_message=body.user_message,
        assistant_response=body.assistant_response,
        source=body.source,
    )
    return {
        "stored": result.stored,
        "id": result.id,
        "reason": result.reason,
        "memory_type": result.memory_type,
        "used_llm": result.used_llm,
        "source_type": result.source_type,
    }


@router.post("/tool-result-v2")
async def memory_tool_result_v2(
    body: ToolResultRequest,
    service: AutoStoreService = Depends(get_auto_store_service),
) -> dict:
    result = await service.store_tool_result(
        session_id=body.session_id,
        tool_name=body.tool_name,
        result=body.result,
        source=body.source,
    )
    return {
        "stored": result.stored,
        "id": result.id,
        "reason": result.reason,
        "memory_type": result.memory_type,
        "used_llm": result.used_llm,
        "source_type": result.source_type,
    }
