# type: ignore[reportAttributeAccessIssue]
"""MemoryRecord API contract tests (23.3).

Verifies backward-compatible aliases for MemoryRecord and repository methods.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from memoryx.storage.repository import MemoryRecord, MemoryRepository


class TestMemoryRecordAlias:
    """MemoryRecord(id=...) and MemoryRecord(memory_id=...) must both work."""

    def test_id_kwarg(self) -> None:
        r = MemoryRecord(id="m1", content="hello")
        assert r.id == "m1"
        assert r.memory_id == "m1"

    def test_memory_id_kwarg(self) -> None:
        r = MemoryRecord(memory_id="m2", content="hello")
        assert r.id == "m2"
        assert r.memory_id == "m2"

    def test_both_id_wins(self) -> None:
        r = MemoryRecord(id="m1", memory_id="m2", content="hello")
        assert r.id == "m1"
        assert r.memory_id == "m1"

    def test_neither_generates_uuid(self) -> None:
        r = MemoryRecord(content="hello")
        assert r.id is not None
        assert len(r.id) == 32  # uuid4 hex
        assert r.memory_id == r.id

    def test_property_returns_id(self) -> None:
        r = MemoryRecord(id="custom-id", content="test")
        assert r.memory_id == r.id
        r.id = "changed"
        assert r.memory_id == "changed"

    def test_memory_id_is_readonly(self) -> None:
        """memory_id property should not be settable."""
        r = MemoryRecord(id="m1", content="test")
        with pytest.raises(AttributeError):
            r.memory_id = "m2"


@pytest.mark.asyncio
async def test_store_memory_with_memory_id(tmp_path: Path) -> None:
    """store_memory must work when MemoryRecord uses memory_id alias."""
    db_path = tmp_path / "alias_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    rec = MemoryRecord(memory_id="alias-test-1", content="Alias test memory", memory_type="FACT")
    mid = await repo.store_memory(rec)
    assert mid == "alias-test-1"

    await repo.close()


@pytest.mark.asyncio
async def test_add_episodic_memory_with_title(tmp_path: Path) -> None:
    """add_episodic_memory(title=...) must work as alias for content."""
    db_path = tmp_path / "episodic_alias_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    rec = MemoryRecord(id="parent-mem", content="parent", memory_type="FACT")
    await repo.store_memory(rec)

    eid = await repo.add_episodic_memory(
        memory_id="parent-mem",
        session_id="s1",
        title="phase 33 event",
        content="implemented hierarchical memory",
        importance_score=0.9,
    )
    assert eid is not None

    await repo.close()


@pytest.mark.asyncio
async def test_add_entity_with_entity_name(tmp_path: Path) -> None:
    """add_entity(entity_name=...) must work as alias for name."""
    db_path = tmp_path / "entity_alias_test.db"
    repo = MemoryRepository(db_path=db_path)
    await repo.open()

    eid = await repo.add_entity(entity_name="Python", entity_type="language")
    assert eid is not None

    await repo.close()


@pytest.mark.asyncio
async def test_no_unbounded_kwargs() -> None:
    """MemoryRecord must NOT use **kwargs — all parameters must be explicit."""
    import inspect
    sig = inspect.signature(MemoryRecord)
    for name, param in sig.parameters.items():
        assert param.kind != inspect.Parameter.VAR_KEYWORD, (
            f"MemoryRecord must not use **kwargs. Found VAR_KEYWORD on parameter '{name}'"
        )