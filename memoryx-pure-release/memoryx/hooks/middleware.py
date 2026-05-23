from __future__ import annotations

from ..events import EventHandler, MemoryEvent, MiddlewareHandler


async def passthrough_middleware(next_handler, *args, **kwargs):
    return await next_handler(*args, **kwargs)


def noop_middleware() -> MiddlewareHandler:
    async def wrapper(event):
        return event
    return wrapper


def conversation_log_middleware(log_store) -> MiddlewareHandler:
    """将用户/助手对话自动写入 L0 对话日志中间件。"""
    async def wrapper(event: MemoryEvent) -> MemoryEvent:
        if event.event_type.value in ("on_user_message", "on_assistant_response"):
            role = "user" if event.event_type.value == "on_user_message" else "assistant"
            content = event.payload.get("content", "")
            session_id = event.session_id or "unknown"
            if content:
                await log_store.log_turn(session_id=session_id, role=role, content=content)
        return event
    return wrapper
