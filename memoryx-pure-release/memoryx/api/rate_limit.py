"""P0-E: 限流与并发保护。

- SlidingWindowRateLimiter: 滑动窗口限流（默认 100 req/60s）
- EmbeddingConcurrencyGate: embedding 并发限制（默认 4）
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request


@dataclass
class SlidingWindowRateLimiter:
    """滑动窗口限流器。

    max_requests: 窗口内最大请求数
    window_seconds: 窗口大小
    """
    max_requests: int = 100
    window_seconds: float = 60.0
    _windows: dict[str, deque[float]] = field(default_factory=dict)

    def _prune(self, key: str, now: float) -> None:
        window = self._windows.get(key)
        if window is None:
            return
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if key not in self._windows:
            self._windows[key] = deque()
        self._prune(key, now)
        window = self._windows[key]
        if len(window) >= self.max_requests:
            return False
        window.append(now)
        return True

    async def __call__(self, request: Request) -> None:
        """FastAPI dependency: raises 429 if rate limit exceeded."""
        client_key = request.client.host if request.client else "unknown"
        if not self.allow(client_key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")


@dataclass
class EmbeddingConcurrencyGate:
    """限制 embedding 并发数，防止打爆 embedding endpoint。

    max_concurrent: 最大并发 embedding 请求数
    """
    max_concurrent: int = 4
    _semaphore: Optional[asyncio.Semaphore] = None

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def acquire(self) -> None:
        if self._semaphore:
            await self._semaphore.acquire()

    def release(self) -> None:
        if self._semaphore:
            self._semaphore.release()

    def __call__(self):
        """Context manager usage: async with gate(): ..."""
        return _EmbeddingGateContext(self)


class _EmbeddingGateContext:
    def __init__(self, gate: EmbeddingConcurrencyGate) -> None:
        self._gate = gate

    async def __aenter__(self):
        await self._gate.acquire()

    async def __aexit__(self, *args):
        self._gate.release()
