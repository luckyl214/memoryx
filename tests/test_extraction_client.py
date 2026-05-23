from __future__ import annotations

import asyncio
from typing import Any

import pytest

from memoryx.extraction import ExtractionRequest, ExtractionSource, GenericLLMExtractionClient


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self._payload = payload
        self.request_info = None
        self.history = ()
        self.headers = {}

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def text(self) -> str:
        return str(self._payload)

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    def post(self, *args, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_generic_client_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GenericLLMExtractionClient(
        base_url="https://example.invalid/v1/extract",
        api_key=os.environ.get("TEST_API_KEY", "test_key"),
        model="generic-model",
        timeout_seconds=0.1,
        retry_attempts=3,
        retry_base_delay=0.0,
        retry_max_delay=0.0,
    )
    fake_session = FakeSession(
        [
            asyncio.TimeoutError(),
            FakeResponse(200, {"memories": []}),
        ]
    )
    monkeypatch.setattr(client, "_build_session", lambda: fake_session)

    result = await client.extract(
        ExtractionRequest(
            session_id="s1",
            sources=[ExtractionSource(kind="user_message", content="remember this", source_message_id="msg")],
        )
    )

    assert result == {"memories": []}
    assert fake_session.calls == 2


@pytest.mark.asyncio
async def test_generic_client_raises_on_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GenericLLMExtractionClient(
        base_url="https://example.invalid/v1/extract",
        api_key=os.environ.get("TEST_API_KEY", "test_key"),
        model="generic-model",
        timeout_seconds=0.1,
        retry_attempts=1,
        retry_base_delay=0.0,
        retry_max_delay=0.0,
    )
    fake_session = FakeSession([FakeResponse(200, {"unexpected": True})])
    monkeypatch.setattr(client, "_build_session", lambda: fake_session)

    with pytest.raises(ValueError):
        await client.extract(
            ExtractionRequest(
                session_id="s1",
                sources=[ExtractionSource(kind="tool_result", content="result", source_message_id="msg")],
            )
        )
