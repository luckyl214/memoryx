from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class AutoStoreResult:
    stored: bool
    id: str | None = None
    reason: str = ""
    memory_type: str | None = None
    used_llm: bool = False
    source_type: str | None = None


class AutoStoreService:
    """
    统一记忆自动写入服务。

    重要：
    - 不直接 INSERT INTO memories。
    - 所有写入都走 MemoryRepository.store_memory。
    - LLM 失败时不影响主流程。
    """

    def __init__(
        self,
        *,
        repository: Any,
        decision_service: Any,
    ) -> None:
        self.repository = repository
        self.decision_service = decision_service

    async def store_conversation_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_response: str,
        source: str = "hermes.post_llm_call",
    ) -> AutoStoreResult:
        decision = await self.decision_service.decide(
            user_message=user_message,
            assistant_response=assistant_response,
            source=source,
        )

        if not decision.should_save:
            return AutoStoreResult(
                stored=False,
                reason=decision.blocked_reason or decision.reason or "not_saved",
                used_llm=decision.used_llm,
            )

        metadata = {
            "session_id": session_id or "default",
            "source": source,
            "decision_reason": decision.reason,
            "tags": decision.tags,
            "source_type": decision.source_type,
            "used_llm": decision.used_llm,
        }

        from memoryx.storage import MemoryRecord

        record = MemoryRecord(
            id=uuid4().hex,
            session_id=session_id or "default",
            memory_type=decision.memory_type,
            content=decision.content,
            importance_score=decision.importance_score,
            confidence_score=decision.confidence_score,
            metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        )

        memory_id = await self.repository.store_memory(record)
        return AutoStoreResult(
            stored=True,
            id=memory_id,
            reason=decision.reason,
            memory_type=decision.memory_type,
            used_llm=decision.used_llm,
            source_type=decision.source_type,
        )

    async def store_tool_result(
        self,
        *,
        session_id: str,
        tool_name: str,
        result: str,
        source: str = "hermes.post_tool_call",
    ) -> AutoStoreResult:
        if not tool_name.strip():
            return AutoStoreResult(stored=False, reason="missing_tool_name")

        content = f"Tool result verified by runtime: {tool_name}\n{result[:2000]}"

        metadata = {
            "session_id": session_id or "default",
            "source": source,
            "tool_name": tool_name,
            "source_type": "tool_verified",
        }

        from memoryx.storage import MemoryRecord

        record = MemoryRecord(
            id=uuid4().hex,
            session_id=session_id or "default",
            memory_type="OBSERVATION",
            content=content,
            importance_score=0.35,
            confidence_score=0.9,
            metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        )

        memory_id = await self.repository.store_memory(record)
        return AutoStoreResult(
            stored=True,
            id=memory_id,
            reason="tool_verified",
            memory_type="OBSERVATION",
            used_llm=False,
            source_type="tool_verified",
        )
