from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryx.reinforcement import ImportanceReinforcementEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_reinforcement_boosts_high_access_memory(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reinforce-access.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m1", memory_type="FACT", content="High access memory", access_count=6, importance_score=0.5, reinforcement_score=0.1))

    engine = ImportanceReinforcementEngine(repository=repo)
    updated = await engine.run_cycle()

    record = await repo.get_memory("m1")
    assert updated >= 1
    assert record is not None
    assert float(record["reinforcement_score"]) > 0.1
    await repo.close()


@pytest.mark.asyncio
async def test_reinforcement_boosts_project_relevant_memory(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reinforce-project.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m2", memory_type="PROJECT", content="Critical Mnemosyne-X design memory", importance_score=0.7, reinforcement_score=0.0, scope="project", entities_json=json.dumps(["Mnemosyne-X"])))

    engine = ImportanceReinforcementEngine(repository=repo)
    await engine.run_cycle(project_keywords=["mnemosyne-x"])

    record = await repo.get_memory("m2")
    assert record is not None
    assert float(record["reinforcement_score"]) > 0.0
    await repo.close()


@pytest.mark.asyncio
async def test_reinforcement_applies_temporal_decay_to_stale_memory(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reinforce-decay.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m3", memory_type="FACT", content="Stale memory", importance_score=0.8, reinforcement_score=0.6, decay_score=0.0, valid_from="2024-01-01T00:00:00+00:00"))

    engine = ImportanceReinforcementEngine(repository=repo)
    await engine.run_cycle(now_iso="2026-01-01T00:00:00+00:00")

    record = await repo.get_memory("m3")
    assert record is not None
    assert float(record["decay_score"]) > 0.0
    await repo.close()


@pytest.mark.asyncio
async def test_reinforcement_boosts_recurrent_preference_memory(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "reinforce-recur.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="m4", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.75, reinforcement_score=0.05, access_count=2))
    await repo.store_memory(MemoryRecord(memory_id="m5", memory_type="PREFERENCE", content="User prefers async Python", importance_score=0.7, reinforcement_score=0.02, access_count=1))

    engine = ImportanceReinforcementEngine(repository=repo)
    await engine.run_cycle()

    record = await repo.get_memory("m4")
    assert record is not None
    assert float(record["reinforcement_score"]) > 0.05
    await repo.close()
