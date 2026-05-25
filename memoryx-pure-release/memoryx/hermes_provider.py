"""Hermes Memory Provider facade.

This class exposes a simple provider-shaped API while delegating to
HermesMemoryBridge. Hermes integrations can call these methods directly or bind
them to plugin hooks.
"""

from __future__ import annotations

from typing import Any

from memoryx.hermes_bridge import HermesMemoryBridge


class MemoryXHermesProvider:
    name = "memoryx"

    def __init__(self, *, bridge: HermesMemoryBridge) -> None:
        self.bridge = bridge

    async def search(self, query: str, *, session_id: str, limit: int = 6) -> list[dict[str, Any]]:
        if self.bridge.query_api is None:
            return []
        return await self.bridge.query_api.search(
            query=query,
            query_vector=[],
            limit=limit,
            session_id=session_id,
            include_global=True,
            include_lessons=True,
            explain_scores=True,
        )

    async def build_context(self, query: str, *, session_id: str) -> str:
        result = await self.bridge.on_user_message(session_id=session_id, content=query)
        return result.context_block

    async def add(self, content: str, *, session_id: str, memory_type: str = "FACT") -> str | None:
        if self.bridge.query_api is not None and hasattr(self.bridge.query_api, "store"):
            return await self.bridge.query_api.store(
                memory_type=memory_type,
                content=content,
                session_id=session_id,
                scope="global",
            )
        return None

    async def guard_tool_call(self, *, session_id: str, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return (await self.bridge.on_tool_call(session_id=session_id, tool_name=tool_name, args=args or {})).to_dict()

    async def verify_response(self, *, session_id: str, question: str, response: str) -> dict[str, Any]:
        return (await self.bridge.on_assistant_response(session_id=session_id, content=response, question=question)).to_dict()

    async def finalize_session(self, *, session_id: str) -> dict[str, Any]:
        return (await self.bridge.on_session_end(session_id=session_id)).to_dict()

    async def shutdown(self) -> None:
        close = getattr(self.bridge.repository, "close", None)
        if close is not None:
            await close()
