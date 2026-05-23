from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.persona import PersonaEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_persona_engine_generates_markdown_from_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "persona-gen.db")
    await repo.open()
    await repo.store_memories([
        MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers async Python",
                     confidence_score=0.9, importance_score=0.85, scope="user"),
        MemoryRecord(memory_id="p2", memory_type="PREFERENCE", content="User prefers async Python",
                     confidence_score=0.92, importance_score=0.9, scope="user"),
        MemoryRecord(memory_id="p3", memory_type="PREFERENCE", content="User dislikes ORM",
                     confidence_score=0.88, importance_score=0.8, scope="user"),
        MemoryRecord(memory_id="p4", memory_type="PROJECT", content="Project principle: avoid heavy frameworks",
                     scope="project", tags_json='["workflow"]'),
    ])

    engine = PersonaEngine(repository=repo)
    result = await engine.generate()

    assert "Stable Preferences" in result["markdown"]
    assert "async Python" in result["markdown"]
    assert "Project Principles" in result["markdown"]
    assert "heavy frameworks" in result["markdown"]
    assert "Generated" in result["markdown"]
    assert result["source_count"] >= 3
    await repo.close()


@pytest.mark.asyncio
async def test_persona_engine_persists_to_reflection_summaries(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "persona-persist.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="prefers testing first",
                                         confidence_score=0.9, importance_score=0.85))
    await repo.store_memory(MemoryRecord(memory_id="p2", memory_type="PREFERENCE", content="prefers testing first",
                                         confidence_score=0.91, importance_score=0.9))

    engine = PersonaEngine(repository=repo)
    result = await engine.generate(persist=True)
    rows = await repo.db.fetchall("SELECT summary FROM reflection_summaries ORDER BY created_at DESC LIMIT 1;")

    assert rows
    assert "prefers testing first" in rows[0]["summary"]
    await repo.close()


@pytest.mark.asyncio
async def test_persona_engine_empty_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "persona-empty.db")
    await repo.open()

    engine = PersonaEngine(repository=repo)
    result = await engine.generate()

    assert "Generated" in result["markdown"]
    assert result["source_count"] == 0
    assert result["stable_preferences"] == []
    await repo.close()
