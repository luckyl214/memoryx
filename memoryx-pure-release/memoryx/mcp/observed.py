"""MCP observability helpers."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from memoryx.observability import mcp_tool_calls_total


def observe_mcp_tool(tool_name: str):
    """Decorator for async MCP tool handlers."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            status = "ok"
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                mcp_tool_calls_total.labels(tool=tool_name, status=status).inc()
        return wrapper
    return decorator


def instrument_mcp_server(server: Any, tool_names: list[str] | None = None) -> Any:
    """Best-effort instance-level MCP tool instrumentation.

    If the server exposes call_<tool> methods, this wraps them. Otherwise this is
    a no-op and tests can still use observe_mcp_tool directly.
    """
    names = tool_names or ["memoryx_search", "memoryx_feedback", "memoryx_timeline"]
    for name in names:
        method_name = f"call_{name}"
        if not hasattr(server, method_name):
            continue
        method = getattr(server, method_name)
        if getattr(method, "_memoryx_mcp_observed", False):
            continue
        wrapped = observe_mcp_tool(name)(method)
        wrapped._memoryx_mcp_observed = True  # type: ignore[attr-defined]
        setattr(server, method_name, wrapped)
    return server
