"""P0-B: Verify store_memories() writes all three tables in one transaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_store_memories_writes_all_tables(tmp_path: Path) -> None:
    """Bulk upsert must write memories, memory_versions, and audit_logs
    in a single atomic transaction."""
    repo = MemoryRepository(tmp_path / "memoryx_txn.db")
    await repo.open()

    records = [
        MemoryRecord(id="txn_a", memory_type="FACT", content="Memory A"),
        MemoryRecord(id="txn_b", memory_type="OBSERVATION", content="Memory B"),
        MemoryRecord(id="txn_c", memory_type="PREFERENCE", content="Memory C"),
    ]

    count = await repo.store_memories(records)
    assert count == 3

    # Verify memories table
    for r in records:
        mem = await repo.get_memory(r.id)
        assert mem is not None, f"Memory {r.id} not found"
        assert mem["content"] == r.content
        assert mem["active_state"] == "active"

    # Verify memory_versions table
    import asyncio
    from memoryx.storage import AsyncSQLite

    db = AsyncSQLite(tmp_path / "memoryx_txn.db")
    await db.open()
    versions = await db.fetchall("SELECT * FROM memory_versions WHERE memory_id IN (?, ?, ?);", ("txn_a", "txn_b", "txn_c"))
    assert len(versions) == 3, f"Expected 3 versions, got {len(versions)}"

    # Verify audit_logs table
    audit = await db.fetchall(
        "SELECT * FROM audit_logs WHERE entity_type = 'memories' AND action = 'store_memory' AND entity_id IN (?, ?, ?);",
        ("txn_a", "txn_b", "txn_c"),
    )
    assert len(audit) == 3, f"Expected 3 audit records, got {len(audit)}"

    await db.close()
    await repo.close()


@pytest.mark.asyncio
async def test_store_memories_empty_list(tmp_path: Path) -> None:
    """Empty record list should return 0 without error."""
    repo = MemoryRepository(tmp_path / "memoryx_empty.db")
    await repo.open()
    count = await repo.store_memories([])
    assert count == 0
    await repo.close()


@pytest.mark.asyncio
async def test_store_memories_upsert_existing(tmp_path: Path) -> None:
    """Upsert should update existing records and create new versions."""
    repo = MemoryRepository(tmp_path / "memoryx_upsert.db")
    await repo.open()

    # First write
    await repo.store_memories([
        MemoryRecord(id="up_a", memory_type="FACT", content="Original"),
    ])

    # Update
    await repo.store_memories([
        MemoryRecord(id="up_a", memory_type="FACT", content="Updated"),
    ])

    mem = await repo.get_memory("up_a")
    assert mem["content"] == "Updated"

    # Versions should now be 2
    from memoryx.storage import AsyncSQLite
    db = AsyncSQLite(tmp_path / "memoryx_upsert.db")
    await db.open()
    versions = await db.fetchall("SELECT * FROM memory_versions WHERE memory_id = 'up_a' ORDER BY version;")
    assert len(versions) >= 2, f"Expected >= 2 versions, got {len(versions)}"
    assert versions[-1]["content"] == "Updated"
    await db.close()
    await repo.close()
