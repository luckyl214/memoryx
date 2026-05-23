from __future__ import annotations

from typing import Optional

from ..events import MemoryEventType


class SessionEventListener:
    def __init__(self, manager) -> None:
        self._manager = manager

    async def on_user_message(self, session_id: str, content: str, **extra) -> None:
        await self._manager.emit(MemoryEventType.ON_USER_MESSAGE, session_id, {"content": content, **extra})

    async def on_assistant_response(self, session_id: str, content: str, **extra) -> None:
        await self._manager.emit(MemoryEventType.ON_ASSISTANT_RESPONSE, session_id, {"content": content, **extra})

    async def on_tool_call(self, session_id: str, tool_name: str, args: dict, **extra) -> None:
        await self._manager.emit(
            MemoryEventType.ON_TOOL_CALL,
            session_id,
            {"tool_name": tool_name, "args": args, **extra},
        )

    async def on_tool_result(self, session_id: str, tool_name: str, result: dict | str, **extra) -> None:
        await self._manager.emit(
            MemoryEventType.ON_TOOL_RESULT,
            session_id,
            {"tool_name": tool_name, "result": result, **extra},
        )

    async def on_session_end(self, session_id: str, **extra) -> None:
        await self._manager.emit(MemoryEventType.ON_SESSION_END, session_id, extra)
