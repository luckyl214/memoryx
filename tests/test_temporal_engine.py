from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from memoryx.temporal import TemporalMemoryEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_temporal_engine_reconstructs_timeline(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "temporal.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="t1", memory_type="FACT", content="v1", valid_from="2025-01-01T00:00:00+00:00", scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="t1", memory_type="FACT", content="v2", valid_from="2025-02-01T00:00:00+00:00", scope="project", checksum=""))

    engine = TemporalMemoryEngine(repository=repo)
    timeline = await engine.timeline("t1")

    assert timeline[0].content == "v1"
    assert timeline[-1].content == "v2"
    await repo.close()


@pytest.mark.asyncio
async def test_temporal_engine_returns_active_state_at_point_in_time(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "temporal-point.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="t2", memory_type="PROJECT", content="current", valid_from="2025-03-01T00:00:00+00:00", scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="t2", memory_type="PROJECT", content="superseded", valid_from="2025-04-01T00:00:00+00:00", valid_to="2025-04-30T00:00:00+00:00", active_state=0, scope="project", checksum=""))

    engine = TemporalMemoryEngine(repository=repo)
    result = await engine.at_time("t2", "2025-03-15T00:00:00+00:00")

    assert result is not None
    assert result.content == "current"
    await repo.close()


@pytest.mark.asyncio
async def test_temporal_engine_supersedes_old_version(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "temporal-supersede.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="old", memory_type="FACT", content="old version", scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="new", memory_type="FACT", content="new version", scope="project"))

    engine = TemporalMemoryEngine(repository=repo)
    await engine.supersede("old", "new")

    old_record = await repo.get_memory("old")
    assert old_record is not None
    assert int(old_record["active_state"]) == 0
    assert old_record["superseded_by"] == "new"
    await repo.close()


@pytest.mark.asyncio
async def test_temporal_engine_lists_historical_states(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "temporal-history.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(memory_id="h1", memory_type="TASK", content="first", scope="project"))
    await repo.store_memory(MemoryRecord(memory_id="h1", memory_type="TASK", content="second", scope="project"))

    engine = TemporalMemoryEngine(repository=repo)
    history = await engine.history("h1")

    assert len(history) >= 2
    assert history[0].content == "first"
    assert history[-1].content == "second"
    await repo.close()
