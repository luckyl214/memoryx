from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.reflection import ReflectionEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_reflection_detects_stable_preferences(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reflection-pref.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="r1", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.8))
    await repo.store_memory(MemoryRecord(memory_id="r2", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.82))

    engine = ReflectionEngine(repository=repo)
    report = await engine.generate_reflection()

    assert "stable_preferences" in report
    assert any("async Python" in item for item in report["stable_preferences"])
    await repo.close()


@pytest.mark.asyncio
async def test_reflection_detects_recurring_issues(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reflection-issues.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="r3", memory_type="EXPERIENCE", content="Deployment incident caused rollback", importance_score=0.9, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="r4", memory_type="EXPERIENCE", content="Another deployment incident required rollback", importance_score=0.88, scope="project"))

    engine = ReflectionEngine(repository=repo)
    report = await engine.generate_reflection()

    assert any("deployment incident" in item.lower() or "rollback" in item.lower() for item in report["recurring_issues"])
    await repo.close()


@pytest.mark.asyncio
async def test_reflection_tracks_project_evolution(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reflection-project.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="r5", memory_type="PROJECT", content="Phase 1 added hook layer", importance_score=0.8, scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="r6", memory_type="PROJECT", content="Phase 2 added SQLite schema", importance_score=0.85, scope="project"))

    engine = ReflectionEngine(repository=repo)
    report = await engine.generate_reflection()

    assert len(report["project_evolution"]) >= 2
    await repo.close()


@pytest.mark.asyncio
async def test_reflection_persists_summary(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reflection-persist.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="r7", memory_type="PROJECT", content="Workflow uses async queue", importance_score=0.81, scope="project", tags_json=json.dumps(["workflow"])))

    engine = ReflectionEngine(repository=repo)
    report = await engine.generate_reflection()

    rows = await repo.db.fetchall("SELECT summary FROM reflection_summaries;", ())
    assert report["summary"]
    assert len(rows) == 1
    await repo.close()
