from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from memoryx.extraction import ExtractionRequest, ExtractionSource, GenericLLMExtractionClient, MemoryExtractionEngine


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        self.calls.append({"session_id": request.session_id, "messages": len(request.sources)})
        return self.payload


@pytest.mark.asyncio
async def test_engine_normalizes_structured_memories() -> None:
    client = FakeClient(
        {
            "memories": [
                {
                    "memory_type": "PREFERENCE",
                    "content": "User prefers async Python code",
                    "importance_score": 0.91,
                    "confidence_score": 0.95,
                    "entities": ["user", "Python"],
                    "tags": ["preference", "coding"],
                    "scope": "user",
                    "timestamp": "2026-05-22T09:13:00+00:00",
                    "source_message_id": "msg-1",
                    "reasoning": "Repeated direct preference",
                }
            ]
        }
    )
    engine = MemoryExtractionEngine(client=client)
    request = ExtractionRequest(
        session_id="s1",
        sources=[ExtractionSource(kind="user_message", content="我喜欢 async Python", source_message_id="msg-1")],
    )

    result = await engine.extract(request)

    assert len(result.memories) == 1
    memory = result.memories[0]
    assert memory.memory_type == "PREFERENCE"
    assert memory.entities == ["user", "Python"]
    assert memory.scope == "user"
    assert memory.source_message_id == "msg-1"
    assert client.calls[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_engine_filters_low_value_chat() -> None:
    client = FakeClient(
        {
            "memories": [
                {
                    "memory_type": "FACT",
                    "content": "hello",
                    "importance_score": 0.1,
                    "confidence_score": 0.2,
                    "entities": [],
                    "tags": [],
                    "scope": "session",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_message_id": "msg-2",
                    "reasoning": "Small talk only",
                }
            ]
        }
    )
    engine = MemoryExtractionEngine(client=client, min_importance=0.3, min_confidence=0.4)

    result = await engine.extract(
        ExtractionRequest(
            session_id="s2",
            sources=[ExtractionSource(kind="assistant_response", content="你好呀", source_message_id="msg-2")],
        )
    )

    assert result.memories == []


@pytest.mark.asyncio
async def test_engine_batches_sources() -> None:
    client = FakeClient({"memories": []})
    engine = MemoryExtractionEngine(client=client, batch_size=2)
    request = ExtractionRequest(
        session_id="s3",
        sources=[
            ExtractionSource(kind="user_message", content="A", source_message_id="1"),
            ExtractionSource(kind="assistant_response", content="B", source_message_id="2"),
            ExtractionSource(kind="tool_result", content="C", source_message_id="3"),
        ],
    )

    await engine.extract(request)

    assert len(client.calls) == 2


def test_generic_client_prompt_contains_required_categories() -> None:
    prompt = GenericLLMExtractionClient.build_prompt(
        ExtractionRequest(
            session_id="s4",
            sources=[ExtractionSource(kind="user_message", content="Remember my coding style", source_message_id="m4")],
        )
    )

    assert "user preferences" in prompt
    assert "project context" in prompt
    assert "debugging history" in prompt
    assert "structured JSON" in prompt
