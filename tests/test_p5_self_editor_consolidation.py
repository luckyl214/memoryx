"""P5: SelfEditor + LLMConsolidationEngine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.self_editor import SelfEditRequest, SelfEditor
from memoryx.llm_consolidation_engine import LLMConsolidationEngine
from memoryx.storage import MemoryRecord, MemoryRepository


# ── SelfEditor ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_self_editor_preview_correct(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "se1.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="s1", memory_type="FACT", content="old fact"))

    editor = SelfEditor(repository=repo)
    preview = await editor.preview(SelfEditRequest(
        memory_id="s1", edit_type="correct",
        changes={"content": "new fact"}, reason="updated",
    ))
    assert preview.edit_type == "correct"
    assert preview.after["content"] == "new fact"
    await repo.close()


@pytest.mark.asyncio
async def test_self_editor_apply_correct(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "se2.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="s2", memory_type="FACT", content="old"))

    editor = SelfEditor(repository=repo)
    result = await editor.apply(SelfEditRequest(
        memory_id="s2", edit_type="correct",
        changes={"content": "corrected"}, reason="fix",
    ))
    assert result.applied

    mem = await repo.get_memory("s2")
    assert mem["content"] == "corrected"
    await repo.close()


@pytest.mark.asyncio
async def test_self_editor_preview_forget(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "se3.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="s3", memory_type="OBSERVATION", content="forget me"))

    editor = SelfEditor(repository=repo)
    preview = await editor.preview(SelfEditRequest(
        memory_id="s3", edit_type="forget", reason="irrelevant",
    ))
    assert preview.edit_type == "forget"
    assert preview.after["active_state"] == "archived"
    await repo.close()


@pytest.mark.asyncio
async def test_self_editor_invalid_type(tmp_path: Path):
    with pytest.raises(ValueError, match="edit_type"):
        SelfEditRequest(memory_id="x", edit_type="invalid")


# ── LLMConsolidationEngine ───────────────────────────────────────

@pytest.mark.asyncio
async def test_consolidation_dry_run(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "cons1.db")
    await repo.open()
    # Create a decayed, unaccessed memory that should be flagged for archive
    await repo.store_memory(MemoryRecord(
        id="c1", memory_type="OBSERVATION", content="stale data",
        decay_score=0.98, access_count=0, confidence_score=0.1,
    ))
    await repo.store_memory(MemoryRecord(
        id="c2", memory_type="FACT", content="current data",
        decay_score=0.1, access_count=5, confidence_score=0.9,
    ))

    engine = LLMConsolidationEngine(repository=repo)
    result = await engine.run(limit=50, dry_run=True)

    assert result.dry_run
    assert result.total_candidates == 2
    assert result.archived >= 1  # c1 should be flagged
    await repo.close()


@pytest.mark.asyncio
async def test_consolidation_apply(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "cons2.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(
        id="ca1", memory_type="OBSERVATION", content="stale",
        decay_score=0.99, access_count=0,
    ))

    engine = LLMConsolidationEngine(repository=repo)
    result = await engine.run(limit=50, dry_run=False)

    assert not result.dry_run
    mem = await repo.get_memory("ca1")
    assert mem["active_state"] == "archived"
    await repo.close()
