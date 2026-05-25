"""MemoryX observability package.

P8 goals:
- Trace context propagated across REST / Event / Retrieval paths.
- Prometheus metrics for REST, retrieval stages, lessons, feedback, MCP.
- Lightweight helpers that degrade cleanly if prometheus-client is absent.
"""

from __future__ import annotations

from .context import (
    bind_observability_context,
    clear_observability_context,
    current_session_id,
    current_trace_id,
    new_trace_id,
)
from .metrics import (
    CONTENT_TYPE_LATEST,
    feedback_events_total,
    lesson_boost_score,
    lesson_match_total,
    mcp_tool_calls_total,
    metrics_response_bytes,
    rest_request_seconds,
    rest_requests_total,
    retrieval_stage_seconds,
)
from .timing import observe_stage, observe_stage_async

__all__ = [
    "CONTENT_TYPE_LATEST",
    "bind_observability_context",
    "clear_observability_context",
    "current_session_id",
    "current_trace_id",
    "feedback_events_total",
    "lesson_boost_score",
    "lesson_match_total",
    "mcp_tool_calls_total",
    "metrics_response_bytes",
    "new_trace_id",
    "observe_stage",
    "observe_stage_async",
    "rest_request_seconds",
    "rest_requests_total",
    "retrieval_stage_seconds",
]

# backward-compat: P0 observability engine
from .engine import MemoryObservabilityEngine  # noqa: E402,F401
__all__.append("MemoryObservabilityEngine")
