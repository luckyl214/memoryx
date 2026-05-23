"""Prometheus-compatible metrics for MemoryX.

If prometheus-client is unavailable, these metrics degrade to no-ops so the
library remains importable for minimal installations.
"""

from __future__ import annotations

try:  # pragma: no cover - depends on optional runtime package
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except Exception:  # pragma: no cover
    Counter = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _NoopMetric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs) -> None:
        return None

    def observe(self, *args, **kwargs) -> None:
        return None


def _counter(name: str, doc: str, labels: list[str] | None = None):
    if Counter is None:
        return _NoopMetric()
    return Counter(name, doc, labels or [])


def _histogram(name: str, doc: str, labels: list[str] | None = None, buckets=None):
    if Histogram is None:
        return _NoopMetric()
    kwargs = {"buckets": buckets} if buckets is not None else {}
    return Histogram(name, doc, labels or [], **kwargs)


_LATENCY_BUCKETS = (
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)

_SCORE_BUCKETS = (0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0)

rest_requests_total = _counter(
    "memoryx_rest_requests_total",
    "MemoryX REST requests by route/method/status.",
    ["route", "method", "status_code"],
)

rest_request_seconds = _histogram(
    "memoryx_rest_request_seconds",
    "MemoryX REST request latency in seconds.",
    ["route", "method"],
    _LATENCY_BUCKETS,
)

retrieval_stage_seconds = _histogram(
    "memoryx_retrieval_stage_seconds",
    "MemoryX retrieval stage latency in seconds.",
    ["stage"],
    _LATENCY_BUCKETS,
)

retrieval_results_total = _counter(
    "memoryx_retrieval_results_total",
    "MemoryX retrieval result count bucketed by source.",
    ["source"],
)

lesson_match_total = _counter(
    "memoryx_lesson_match_total",
    "LESSON matches during retrieval.",
    ["policy_type"],
)

lesson_boost_score = _histogram(
    "memoryx_lesson_boost_score",
    "LESSON boost score distribution.",
    ["policy_type"],
    _SCORE_BUCKETS,
)

feedback_events_total = _counter(
    "memoryx_feedback_events_total",
    "Feedback events by polarity and application mode.",
    ["positive", "dry_run"],
)

mcp_tool_calls_total = _counter(
    "memoryx_mcp_tool_calls_total",
    "MCP tool calls by tool name and status.",
    ["tool", "status"],
)


def metrics_response_bytes() -> bytes:
    if generate_latest is None:
        return b"# prometheus_client not installed\n"
    return generate_latest()
