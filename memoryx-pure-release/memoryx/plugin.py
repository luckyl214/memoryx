from __future__ import annotations

import asyncio
from typing import Any

from .events import MemoryEventType
from .manager import MemoryHookManager


def register(ctx) -> None:
    settings = getattr(ctx, "memoryx_settings", None)
    if settings is None:
        from .config import get_settings

        settings = get_settings()

    from .logging import configure_logging, get_logger

    settings.ensure_directories()
    configure_logging(
        settings.logs_dir,
        settings.log_level,
        max_bytes=settings.log_rotation_bytes,
        backup_count=settings.log_backup_count,
    )
    logger = get_logger("memoryx")
    manager = MemoryHookManager(settings=settings, logger=logger)
    ctx.memoryx_manager = manager
    ctx.memoryx_listener = manager.listener

    def _enqueue(event_type: MemoryEventType, session_id, payload):
        return manager.emit(event_type, session_id, payload)

    def _fire_and_forget(coro):
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    ctx.register_hook("on_user_message", lambda **kw: _enqueue(MemoryEventType.ON_USER_MESSAGE, kw.get("session_id"), kw))
    ctx.register_hook("on_assistant_response", lambda **kw: _enqueue(MemoryEventType.ON_ASSISTANT_RESPONSE, kw.get("session_id"), kw))
    ctx.register_hook("on_tool_call", lambda **kw: _enqueue(MemoryEventType.ON_TOOL_CALL, kw.get("session_id"), kw))
    ctx.register_hook("on_tool_result", lambda **kw: _enqueue(MemoryEventType.ON_TOOL_RESULT, kw.get("session_id"), kw))
    ctx.register_hook("on_session_end", lambda **kw: _enqueue(MemoryEventType.ON_SESSION_END, kw.get("session_id"), kw))

    if hasattr(ctx, "register_middleware"):
        ctx.register_middleware(manager.middleware)

    async def _startup() -> None:
        await manager.start()

    _fire_and_forget(_startup())

    async def _shutdown(**kwargs: Any) -> None:
        await manager.stop()

    ctx.register_hook("on_session_finalize", _shutdown)
