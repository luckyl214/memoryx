"""Lightweight observability primitives for MemoryX."""

from __future__ import annotations

import contextlib
import time
from typing import Iterator

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except Exception:
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

    @contextlib.contextmanager
    def time(self) -> Iterator[None]:
        yield


if Histogram is not None:
    retrieval_stage_seconds = Histogram(
        "memoryx_retrieval_stage_seconds",
        "MemoryX retrieval stage latency in seconds",
        ["stage"],
    )
    lesson_boost_score = Histogram(
        "memoryx_lesson_boost_score",
        "Distribution of boost scores applied to LESSON memories",
    )
else:
    retrieval_stage_seconds = _NoopMetric()
    lesson_boost_score = _NoopMetric()

if Counter is not None:
    rest_requests_total = Counter(
        "memoryx_rest_requests_total",
        "MemoryX REST requests by route and status code",
        ["route", "status_code"],
    )
    lesson_match_total = Counter(
        "memoryx_lesson_match_total",
        "Total matched lessons during retrieval",
        ["policy_type"],
    )
else:
    rest_requests_total = _NoopMetric()
    lesson_match_total = _NoopMetric()


@contextlib.contextmanager
def observe_stage(stage: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        retrieval_stage_seconds.labels(stage=stage).observe(time.perf_counter() - start)


def metrics_response_bytes() -> bytes:
    if generate_latest is None:
        return b"# prometheus_client is not installed\n"
    return generate_latest()
