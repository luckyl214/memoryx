import pytest
from pathlib import Path

from memoryx.services.task_service import TaskService
from memoryx.storage import MemoryRepository


@pytest.mark.asyncio
async def test_task_start_and_end(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "memoryx.db")
    await repo.open()

    try:
        service = TaskService(repository=repo)

        # Create parent rows for FK constraint (sessions + entities)
        await repo.db.execute(
            "INSERT OR IGNORE INTO sessions(session_id, title, start_time) VALUES (?, ?, datetime('now'));",
            ("s1", "test session"))
        entity_id = await repo.add_entity("memoryx", "agent")

        start = await service.start_task(
            session_id="s1",
            entity_id=entity_id,
            task_type="coding",
            title="Refactor auto store",
        )

        assert start.status == "running"

        end = await service.end_task(
            session_id="s1",
            entity_id=entity_id,
            status="done",
            summary="completed",
        )

        assert end.ended is True
        assert end.task_id == start.task_id
        assert end.duration_seconds >= 0
    finally:
        await repo.close()
