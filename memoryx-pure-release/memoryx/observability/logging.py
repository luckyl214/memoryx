"""Trace-aware structlog helpers."""

from __future__ import annotations

from typing import Any

from .context import current_session_id, current_trace_id


def add_observability_context(logger, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    trace_id = current_trace_id()
    session_id = current_session_id()
    if trace_id and "trace_id" not in event_dict:
        event_dict["trace_id"] = trace_id
    if session_id and "session_id" not in event_dict:
        event_dict["session_id"] = session_id
    return event_dict


def bind_logger(logger):
    """Bind current trace/session to a structlog logger."""
    trace_id = current_trace_id()
    session_id = current_session_id()
    if trace_id:
        logger = logger.bind(trace_id=trace_id)
    if session_id:
        logger = logger.bind(session_id=session_id)
    return logger
