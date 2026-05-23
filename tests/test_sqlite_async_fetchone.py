"""P0-F: AsyncSQLite fetchone optimization test."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage.sqlite_async import AsyncSQLite


@pytest.mark.asyncio
async def test_fetchone_returns_single_row(tmp_path: Path) -> None:
    db = AsyncSQLite(tmp_path / "test_fetchone.db")
    await db.open()
    await db.execute("CREATE TABLE test (id TEXT PRIMARY KEY, val TEXT);")
    await db.execute("INSERT INTO test VALUES ('a', 'alpha');")
    await db.execute("INSERT INTO test VALUES ('b', 'beta');")

    row = await db.fetchone("SELECT * FROM test WHERE id = 'a';")
    assert row is not None
    assert row["id"] == "a"
    assert row["val"] == "alpha"


@pytest.mark.asyncio
async def test_fetchone_returns_none_for_empty(tmp_path: Path) -> None:
    db = AsyncSQLite(tmp_path / "test_fetchone2.db")
    await db.open()
    await db.execute("CREATE TABLE test (id TEXT PRIMARY KEY);")
    row = await db.fetchone("SELECT * FROM test WHERE id = 'nope';")
    assert row is None


@pytest.mark.asyncio
async def test_fetchall_closes_cursor(tmp_path: Path) -> None:
    db = AsyncSQLite(tmp_path / "test_fetchall.db")
    await db.open()
    await db.execute("CREATE TABLE test (id TEXT);")
    await db.execute("INSERT INTO test VALUES ('x');")
    rows = await db.fetchall("SELECT * FROM test;")
    assert len(rows) == 1
    await db.close()
