from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest

from memoryx.config import MemoryXSettings
from memoryx.events import MemoryEventType
from memoryx.plugin import register


class DummyContext:
    def __init__(self) -> None:
        self.memoryx_settings = MemoryXSettings(home=Path(tempfile.mkdtemp(prefix="memoryx-plugin-")), workers=1, queue_size=16)
        self.hooks: dict[str, Callable[..., Awaitable[None]]] = {}
        self.middlewares: list[object] = []
        self.memoryx_manager: Any = None
        self.memoryx_listener: Any = None

    def register_hook(self, name: str, handler: Callable[..., Awaitable[None]]) -> None:
        self.hooks[name] = handler

    def register_middleware(self, middleware) -> None:
        self.middlewares.append(middleware)


@pytest.mark.asyncio
async def test_register_binds_required_hooks_and_shutdown() -> None:
    ctx = DummyContext()
    register(ctx)

    required_hooks = {
        "on_user_message",
        "on_assistant_response",
        "on_tool_call",
        "on_tool_result",
        "on_session_end",
        "on_session_finalize",
    }
    assert required_hooks.issubset(ctx.hooks.keys())
    assert len(ctx.middlewares) == 1

    seen: list[MemoryEventType] = []

    async def handler(event) -> None:
        seen.append(event.event_type)

    await ctx.memoryx_manager.register_handler(MemoryEventType.ON_USER_MESSAGE, handler)
    await asyncio.sleep(0.05)
    await ctx.hooks["on_user_message"](session_id="s1", content="hello")
    await asyncio.sleep(0.05)
    await ctx.hooks["on_session_finalize"]()

    assert seen == [MemoryEventType.ON_USER_MESSAGE]
