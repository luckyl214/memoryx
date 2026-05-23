from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memoryx.cognitive.opinion_shift import OpinionShiftEngine
from memoryx.cognitive.time_axis import EntityTimelineEngine, SessionTaskTracker, TaskDurationEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_taYOUR_API_KEY_HERE(tmp_path):
    repo = MemoryRepository(tmp_path / "timeline.db")
    await repo.open()
    await repo.add_entity("三体", entity_type="book")
    entity = await repo.db.fetchone("SELECT id FROM entities WHERE name = ?;", ("三体",))
    entity_id = entity["id"]

    tracker = SessionTaskTracker(repository=repo)
    task_id = await tracker.start_task(title="读三体", entity_id=entity_id, task_type="reading", ts=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
    seconds = await tracker.end_task(task_id, ts=datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc))
    assert seconds == 9000

    duration = await TaskDurationEngine(repository=repo).duration_for_entity(entity_id=entity_id, task_type="reading")
    assert duration["total_seconds"] == 9000

    timeline = await EntityTimelineEngine(repository=repo).timeline(entity_id=entity_id)
    assert any(item["kind"] == "task_duration" for item in timeline)
    await repo.close()


@pytest.mark.asyncio
async def test_opinion_shift_persists_memory(tmp_path):
    repo = MemoryRepository(tmp_path / "opinion.db")
    await repo.open()
    await repo.add_entity("三体", entity_type="book")
    entity = await repo.db.fetchone("SELECT id FROM entities WHERE name = ?;", ("三体",))
    entity_id = entity["id"]
    await repo.store_memory(MemoryRecord(id="o1", memory_type="OPINION", content="我喜欢三体，剧情很好", valid_from="2024-01-01T00:00:00+00:00"))
    await repo.store_memory(MemoryRecord(id="o2", memory_type="OPINION", content="我对三体评价中性，人物一般", valid_from="2025-01-01T00:00:00+00:00"))
    await repo.db.execute("INSERT INTO memory_entities(memory_id, entity_id) VALUES (?, ?);", ("o1", entity_id))
    await repo.db.execute("INSERT INTO memory_entities(memory_id, entity_id) VALUES (?, ?);", ("o2", entity_id))

    shifts = await OpinionShiftEngine(repository=repo).scan_entity(entity_id=entity_id, dry_run=False)
    assert shifts
    assert shifts[0].memory_id is not None
    stored = await repo.get_memory(shifts[0].memory_id)
    assert stored["memory_type"] == "OPINION_SHIFT"
    await repo.close()
