"""SQLite busy retry policy for concurrent writer scenarios."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass


@dataclass
class SQLiteBusyRetryPolicy:
    max_attempts: int = 5
    base_delay_ms: float = 5.0
    max_delay_ms: float = 100.0
    jitter: bool = True

    async def execute_with_retry(
        self,
        db,
        sql: str,
        params: tuple = (),
    ) -> None:
        """Execute SQL with exponential backoff on SQLITE_BUSY."""
        import sqlite3

        last_exc = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                await db.execute(sql, params)
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                    last_exc = e
                    delay = min(self.base_delay_ms * (2 ** (attempt - 1)), self.max_delay_ms)
                    if self.jitter:
                        delay *= 0.5 + random.random()
                    await asyncio.sleep(delay / 1000.0)
                else:
                    raise
        raise last_exc or RuntimeError("retry exhausted")


# Singleton for shared use
_default_retry = SQLiteBusyRetryPolicy()


async def store_memory_with_retry(repo, record) -> str:
    """Store memory with retry on SQLITE_BUSY."""
    return await retry_call(repo.store_memory, record)


async def update_versioned_with_retry(repo, memory_id: str, changes: dict, **kwargs) -> str:
    """Update with retry."""
    return await retry_call(repo.update_memory_versioned, memory_id, changes, **kwargs)


async def retry_call(fn, *args, **kwargs):
    """Call fn with retry on SQLITE_BUSY."""
    import sqlite3

    for attempt in range(1, _default_retry.max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                if attempt == _default_retry.max_attempts:
                    raise
                delay = min(_default_retry.base_delay_ms * (2 ** (attempt - 1)), _default_retry.max_delay_ms)
                if _default_retry.jitter:
                    delay *= 0.5 + random.random()
                await asyncio.sleep(delay / 1000.0)
            else:
                raise
