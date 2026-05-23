from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp

from .models import ExtractionRequest


class GenericLLMExtractionClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 15.0,
        retry_attempts: int = 3,
        retry_base_delay: float = 0.3,
        retry_max_delay: float = 3.0,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = "your_api_key_here"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._session_factory = session_factory

    @staticmethod
    def build_prompt(request: ExtractionRequest) -> str:
        sections = [
            "You are a production-grade cognitive memory extraction engine.",
            "Extract only long-term valuable memories as structured JSON.",
            "Must recognize: user preferences, project context, coding patterns, recurring issues, emotional intensity, long-term goals, relationships, workflow habits, debugging history, deployment incidents.",
            "Filter low-value chat and small talk.",
            "Return structured JSON with a top-level 'memories' array.",
            "Each memory must include memory_type, content, importance_score, confidence_score, entities, tags, scope, timestamp, source_message_id, reasoning.",
            "Memory types: FACT, EXPERIENCE, OBSERVATION, OPINION, PREFERENCE, PROJECT, TASK, RELATION, EPISODIC.",
            f"Session ID: {request.session_id}",
            "Conversation sources:",
        ]
        for index, source in enumerate(request.sources, start=1):
            sections.append(f"[{index}] kind={source.kind} source_message_id={source.source_message_id or ''} content={source.content}")
        sections.append("Focus on user preferences, project context, debugging history, workflow pattern extraction, and emotional signals.")
        return "\n".join(sections)

    def _build_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        return aiohttp.ClientSession(timeout=timeout)

    async def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        delay = self.retry_base_delay
        payload = {
            "model": self.model,
            "input": self.build_prompt(request),
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.retry_attempts):
            try:
                session = self._build_session()
                if isinstance(session, aiohttp.ClientSession):
                    async with session:
                        return await self._post_and_parse(session, headers, payload)
                return await self._post_and_parse(session, headers, payload)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == self.retry_attempts - 1:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2 if delay > 0 else 0, self.retry_max_delay)

        raise RuntimeError("unreachable")

    async def _post_and_parse(self, session: Any, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        async with session.post(self.base_url, headers=headers, json=payload) as response:
            data = await response.json()
            if response.status >= 400:
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message=await response.text(),
                    headers=response.headers,
                )
            if "memories" not in data or not isinstance(data["memories"], list):
                raise ValueError("Invalid extraction payload: missing 'memories' list")
            return data
