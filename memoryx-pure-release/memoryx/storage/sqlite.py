from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AsyncSQLiteCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    async def fetchone(self):
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self):
        return await asyncio.to_thread(self._cursor.fetchall)

    async def close(self) -> None:
        await asyncio.to_thread(self._cursor.close)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        return False


class AsyncSQLiteConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self._connection.row_factory = value

    async def execute(self, sql: str, parameters: Sequence[Any] | None = None) -> AsyncSQLiteCursor:
        cursor = await asyncio.to_thread(self._connection.execute, sql, parameters or ())
        return AsyncSQLiteCursor(cursor)

    async def executemany(self, sql: str, seq_of_parameters: Iterable[Sequence[Any]]) -> AsyncSQLiteCursor:
        cursor = await asyncio.to_thread(self._connection.executemany, sql, seq_of_parameters)
        return AsyncSQLiteCursor(cursor)

    async def executescript(self, script: str) -> None:
        await asyncio.to_thread(self._connection.executescript, script)

    async def commit(self) -> None:
        await asyncio.to_thread(self._connection.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._connection.rollback)

    async def close(self) -> None:
        await asyncio.to_thread(self._connection.close)


@dataclass(slots=True)
class SQLiteConfig:
    path: Path
    timeout: float = 30.0
    wal_autocheckpoint: int = 1000
    mmap_size: int = 268435456
    cache_size_kib: int = 8192
    synchronous: str = "NORMAL"
    temp_store: str = "MEMORY"
    busy_timeout_ms: int = 5000
    optimize_on_close: bool = True


class AsyncSQLiteDatabase:
    def __init__(self, config: SQLiteConfig) -> None:
        self.config = config
        self._connection: AsyncSQLiteConnection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> AsyncSQLiteConnection:
        async with self._lock:
            if self._connection is not None:
                return self._connection
            self.config.path.parent.mkdir(parents=True, exist_ok=True)
            connection = await asyncio.to_thread(
                sqlite3.connect,
                self.config.path,
                timeout=self.config.timeout,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            wrapped = AsyncSQLiteConnection(connection)
            await self._apply_pragmas(wrapped)
            self._connection = wrapped
            return wrapped

    async def close(self) -> None:
        async with self._lock:
            if self._connection is None:
                return
            if self.config.optimize_on_close:
                await self._connection.execute("PRAGMA optimize;")
            await self._connection.close()
            self._connection = None

    async def _apply_pragmas(self, connection: AsyncSQLiteConnection) -> None:
        pragmas = [
            "PRAGMA journal_mode=WAL;",
            f"PRAGMA synchronous={self.config.synchronous};",
            "PRAGMA foreign_keys=ON;",
            f"PRAGMA wal_autocheckpoint={self.config.wal_autocheckpoint};",
            f"PRAGMA mmap_size={self.config.mmap_size};",
            f"PRAGMA cache_size=-{self.config.cache_size_kib};",
            f"PRAGMA busy_timeout={self.config.busy_timeout_ms};",
            f"PRAGMA temp_store={self.config.temp_store};",
            "PRAGMA auto_vacuum=INCREMENTAL;",
        ]
        for pragma in pragmas:
            await connection.execute(pragma)
        await connection.commit()

    async def executescript(self, script: str) -> None:
        connection = await self.connect()
        await connection.executescript(script)
        await connection.commit()

    async def execute(self, sql: str, parameters: Sequence[Any] | None = None) -> AsyncSQLiteCursor:
        connection = await self.connect()
        cursor = await connection.execute(sql, parameters)
        await connection.commit()
        return cursor

    async def executemany(self, sql: str, seq_of_parameters: Iterable[Sequence[Any]]) -> None:
        connection = await self.connect()
        await connection.executemany(sql, seq_of_parameters)
        await connection.commit()

    async def fetchone(self, sql: str, parameters: Sequence[Any] | None = None) -> dict[str, Any] | None:
        connection = await self.connect()
        cursor = await connection.execute(sql, parameters)
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row is not None else None

    async def fetchall(self, sql: str, parameters: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        connection = await self.connect()
        cursor = await connection.execute(sql, parameters)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSQLiteConnection]:
        connection = await self.connect()
        await connection.execute("BEGIN IMMEDIATE;")
        try:
            yield connection
        except Exception:
            await connection.rollback()
            raise
        else:
            await connection.commit()
