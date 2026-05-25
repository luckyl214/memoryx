"""Trace/session context propagation for MemoryX.

The implementation uses contextvars so async tasks can access trace_id/session_id
without passing them through every function signature.
"""

from __future__ import annotations

import contextvars
from uuid import uuid4

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("memoryx_trace_id", default=None)
_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("memoryx_session_id", default=None)


def new_trace_id() -> str:
    return uuid4().hex


def current_trace_id() -> str | None:
    return _trace_id_var.get()


def current_session_id() -> str | None:
    return _session_id_var.get()


def bind_observability_context(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
) -> tuple[contextvars.Token, contextvars.Token]:
    """Bind trace/session context and return tokens for reset."""
    trace_token = _trace_id_var.set(trace_id or new_trace_id())
    session_token = _session_id_var.set(session_id)
    return trace_token, session_token


def clear_observability_context(tokens: tuple[contextvars.Token, contextvars.Token] | None = None) -> None:
    """Reset context to previous values if tokens were provided."""
    if not tokens:
        _trace_id_var.set(None)
        _session_id_var.set(None)
        return
    trace_token, session_token = tokens
    _trace_id_var.reset(trace_token)
    _session_id_var.reset(session_token)
