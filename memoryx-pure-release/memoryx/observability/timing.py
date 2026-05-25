"""Timing helpers."""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator, Iterator

from .metrics import retrieval_stage_seconds


@contextlib.contextmanager
def observe_stage(stage: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        retrieval_stage_seconds.labels(stage=stage).observe(time.perf_counter() - start)


@contextlib.asynccontextmanager
async def observe_stage_async(stage: str) -> AsyncIterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        retrieval_stage_seconds.labels(stage=stage).observe(time.perf_counter() - start)
