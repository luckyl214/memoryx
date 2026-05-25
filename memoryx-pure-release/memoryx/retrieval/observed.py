"""Instrumentation helpers for HybridRetrievalEngine.

Use this module when modifying the existing retrieval engine directly is too
risky. It wraps an existing engine instance and times known stages when they
exist, while keeping all other attributes delegated.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from memoryx.observability import observe_stage_async, retrieval_stage_seconds


_STAGE_METHODS = {
    "_semantic_candidates": "semantic",
    "_keyword_candidates": "keyword_fts",
    "_fts_candidates": "keyword_fts",
    "_graph_candidates": "graph",
    "_temporal_candidates": "temporal",
    "_merge_lesson_candidates": "lesson_match",
    "_fuse_scores": "fusion",
}


class ObservedRetrievalEngine:
    """Transparent wrapper around an existing retrieval engine."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)

    async def retrieve(self, *args, **kwargs):
        async with observe_stage_async("total"):
            return await self._engine.retrieve(*args, **kwargs)


def instrument_retrieval_engine(engine: Any) -> Any:
    """Patch known stage methods on an engine instance and wrap retrieve total.

    This is intentionally instance-local. It does not mutate the class and can
    be safely used in tests or app wiring.
    """
    for method_name, stage_name in _STAGE_METHODS.items():
        if not hasattr(engine, method_name):
            continue
        method = getattr(engine, method_name)
        if getattr(method, "_memoryx_observed", False):
            continue
        if inspect.iscoroutinefunction(method):
            setattr(engine, method_name, _wrap_async(method, stage_name))
        else:
            setattr(engine, method_name, _wrap_sync(method, stage_name))

    if isinstance(engine, ObservedRetrievalEngine):
        return engine
    return ObservedRetrievalEngine(engine)


def _wrap_async(func: Callable, stage: str) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with observe_stage_async(stage):
            return await func(*args, **kwargs)

    wrapper._memoryx_observed = True  # type: ignore[attr-defined]
    return wrapper


def _wrap_sync(func: Callable, stage: str) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import time

        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            retrieval_stage_seconds.labels(stage=stage).observe(time.perf_counter() - start)

    wrapper._memoryx_observed = True  # type: ignore[attr-defined]
    return wrapper
