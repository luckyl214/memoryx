from __future__ import annotations

import asyncio
import time
from typing import Any

from ..events import MemoryEvent


class RetryManager:
    def __init__(self, retries: int, base_delay: float, max_delay: float, timeout: float) -> None:
        self.retries = retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.retry_count = 0
        self.failure_count = 0

    async def run(self, handler: Any, event: MemoryEvent) -> None:
        delay = self.base_delay
        for attempt in range(self.retries):
            try:
                event.attempt = attempt + 1
                await asyncio.wait_for(handler(event), timeout=self.timeout)
                return
            except Exception as exc:
                self.retry_count += 1
                if attempt == self.retries - 1:
                    self.failure_count += 1
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay)

    def metrics(self) -> dict:
        return {"retry_rate": self.retry_count, "failure_rate": self.failure_count}
