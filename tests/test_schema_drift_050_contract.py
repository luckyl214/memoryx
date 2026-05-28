"""Schema contract test: migration 050 matches db/schema.sql for memory_conflicts.

Ensures that a fresh database can be opened without OperationalError
on the memory_conflicts table's resolved_state column.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from memoryx.storage.repository import MemoryRepository


@pytest.mark.asyncio
async def test_memory_conflicts_schema_contract(tmp_path: Path) -> None:
    """Fresh DB: memory_conflicts table should work with resolved_state column."""
    db_path = tmp_path / "memoryx_contract_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    # Verify the conflict table exists and has resolved_state column
    row = await repo.db.fetchone(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_conflicts';"
    )
    assert row is not None, "memory_conflicts table must exist"
    schema_sql = row["sql"]
    assert "resolved_state" in schema_sql, (
        f"memory_conflicts must have resolved_state column. Got: {schema_sql}"
    )

    # Verify we can insert and query using resolved_state
    # First insert a memory to satisfy FK
    from memoryx.storage.repository import MemoryRecord
    rec = MemoryRecord(
        id="contract-test-memory",
        content="Schema contract test memory",
        memory_type="FACT",
    )
    await repo.store_memory(rec)

    # Insert a conflict
    await repo.add_conflict(
        memory_id="contract-test-memory",
        conflicting_memory_id="contract-test-memory",
        reason="Schema contract self-conflict test"
    )

    # Read it back — should work without OperationalError
    rows = await repo.db.fetchall(
        "SELECT id, resolved_state FROM memory_conflicts WHERE memory_id=?;",
        ("contract-test-memory",)
    )
    assert len(rows) >= 1, "Conflict should be queryable"
    assert rows[0]["resolved_state"] == "open", "Default resolved_state should be 'open'"

    await repo.close()


@pytest.mark.asyncio
async def test_memory_conflicts_index_on_resolved_state(tmp_path: Path) -> None:
    """Fresh DB: index on resolved_state must exist (not on status)."""
    db_path = tmp_path / "memoryx_contract_index_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    rows = await repo.db.fetchall(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='memory_conflicts';"
    )
    index_sqls = [row["sql"] for row in rows if row["sql"] is not None]
    has_status_index = any("status" in sql and "resolved_state" not in sql for sql in index_sqls)
    has_resolved_index = any("resolved_state" in sql for sql in index_sqls)

    assert not has_status_index, (
        f"No index should reference 'status' column. Indexes: {index_sqls}"
    )
    assert has_resolved_index, (
        f"Should have index on resolved_state. Indexes: {index_sqls}"
    )

    await repo.close()


@pytest.mark.asyncio
async def test_memory_conflicts_foreign_key(tmp_path: Path) -> None:
    """FK constraint on memory_conflicts.memory_id must be enforceable."""
    db_path = tmp_path / "memoryx_contract_fk_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    # Check FK is enabled
    pragma = await repo.db.fetchone("PRAGMA foreign_keys;")
    assert pragma is not None, "PRAGMA foreign_keys must return a row"
    assert pragma["foreign_keys"] == 1, "Foreign keys must be enabled"

    # Try inserting a conflict with a nonexistent memory_id — should fail FK
    from uuid import uuid4
    with pytest.raises(Exception) as excinfo:
        await repo.db.execute(
            "INSERT INTO memory_conflicts(id,memory_id,conflicting_memory_id,"
            "contradiction_reason,checksum,resolved_state,created_at,metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?);",
            (uuid4().hex, "nonexistent-id", "nonexistent-id", "FK test",
             "chk", "open", "2024-01-01", "{}")
        )
    assert "FOREIGN KEY" in str(excinfo.value) or "constraint" in str(excinfo.value).lower(), (
        f"Expected FK error, got: {excinfo.value}"
    )

    await repo.close()


@pytest.mark.asyncio
async def test_memory_conflicts_fk_check(tmp_path: Path) -> None:
    """PRAGMA foreign_key_check must pass after schema application."""
    db_path = tmp_path / "memoryx_contract_fkcheck.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    rows = await repo.db.fetchall("PRAGMA foreign_key_check;")
    assert len(rows) == 0, (
        f"foreign_key_check must report 0 violations. Got: {rows}"
    )

    await repo.close()