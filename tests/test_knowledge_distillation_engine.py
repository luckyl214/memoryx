from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.knowledge_distillation import KnowledgeDistillationEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_distillation_extracts_stable_preferences_from_repetition(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "distill-prefs.db")
    await repo.open()
    await repo.store_memories(
        [
            MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers async Python", confidence_score=0.9, importance_score=0.8, scope="user"),
            MemoryRecord(memory_id="p2", memory_type="PREFERENCE", content="User prefers async Python", confidence_score=0.92, importance_score=0.85, scope="user"),
            MemoryRecord(memory_id="p3", memory_type="PREFERENCE", content="User prefers lightweight infrastructure", confidence_score=0.88, importance_score=0.8, scope="user"),
        ]
    )

    engine = KnowledgeDistillationEngine(repository=repo, min_repetitions=2)
    artifact = await engine.distill()

    assert "User prefers async Python" in artifact.stable_preferences
    assert "User prefers lightweight infrastructure" not in artifact.stable_preferences
    assert artifact.source_count == 3
    await repo.close()


@pytest.mark.asyncio
async def test_distillation_abstracts_coding_habits_and_project_principles(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "distill-patterns.db")
    await repo.open()
    await repo.store_memories(
        [
            MemoryRecord(memory_id="w1", memory_type="PROJECT", content="Project uses async queue workers with retry and backoff", tags_json='["workflow"]', scope="project"),
            MemoryRecord(memory_id="w2", memory_type="TASK", content="Debugging pattern: inspect real exports before patching", tags_json='["workflow"]', scope="project"),
            MemoryRecord(memory_id="w3", memory_type="PROJECT", content="Project principle: avoid ORM and heavyweight framework", scope="project"),
        ]
    )

    engine = KnowledgeDistillationEngine(repository=repo)
    artifact = await engine.distill()

    assert any("inspect real exports" in habit for habit in artifact.coding_habits)
    assert any("avoid ORM" in principle for principle in artifact.project_principles)
    assert artifact.semantic_abstractions
    await repo.close()


@pytest.mark.asyncio
async def test_distillation_persists_summary_to_reflection_table(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "distill-summary.db")
    await repo.open()
    await repo.store_memories(
        [
            MemoryRecord(memory_id="p1", memory_type="PREFERENCE", content="User prefers concise responses", confidence_score=0.9, importance_score=0.9),
            MemoryRecord(memory_id="p2", memory_type="PREFERENCE", content="User prefers concise responses", confidence_score=0.91, importance_score=0.9),
        ]
    )

    engine = KnowledgeDistillationEngine(repository=repo, min_repetitions=2)
    artifact = await engine.distill(persist=True)
    rows = await repo.db.fetchall("SELECT summary FROM reflection_summaries ORDER BY created_at DESC LIMIT 1;")

    assert artifact.summary.startswith("Stable profile:")
    assert rows
    assert "concise responses" in rows[0]["summary"]
    await repo.close()
