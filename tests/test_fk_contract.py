"""P1: FK contract tests — verify foreign key constraints are satisfied."""
from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_palace_tunnel_fk_satisfied(tmp_path: Path) -> None:
    """add_tunnel() must create valid FK: palace_tunnels → palace_rooms."""
    from memoryx.palace.engine import PalaceEngine
    repo = MemoryRepository(tmp_path / "fk-palace.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    w1 = await engine.ensure_wing("wing-a")
    w2 = await engine.ensure_wing("wing-b")
    await engine.add_tunnel(w1.wing_id, w2.wing_id)

    # Verify tunnel was created with valid room FK
    rows = await repo.db.fetchall("SELECT * FROM palace_tunnels;")
    assert rows, "no tunnels created"
    for row in rows:
        src = row["source_room_id"]
        tgt = row["target_room_id"]
        src_room = await repo.db.fetchone("SELECT id FROM palace_rooms WHERE id = ?;", (src,))
        tgt_room = await repo.db.fetchone("SELECT id FROM palace_rooms WHERE id = ?;", (tgt,))
        assert src_room, f"source_room_id {src} has no parent in palace_rooms"
        assert tgt_room, f"target_room_id {tgt} has no parent in palace_rooms"
    await repo.close()


@pytest.mark.asyncio
async def test_palace_traverse_through_tunnels(tmp_path: Path) -> None:
    """traverse() must find wings connected via tunnels."""
    from memoryx.palace.engine import PalaceEngine
    repo = MemoryRepository(tmp_path / "fk-palace-traverse.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    w1 = await engine.ensure_wing("alpha")
    w2 = await engine.ensure_wing("beta")
    w3 = await engine.ensure_wing("gamma")
    await engine.add_tunnel(w1.wing_id, w2.wing_id)
    await engine.add_tunnel(w2.wing_id, w3.wing_id)

    results = await engine.traverse("alpha", depth=3)
    names = {r["name"] for r in results}
    assert "alpha" in names
    assert "beta" in names
    assert "gamma" in names
    await repo.close()


@pytest.mark.asyncio
async def test_task_fk_session_exists(tmp_path: Path) -> None:
    """tasks.session_id FK must reference existing session."""
    from memoryx.services.task_service import TaskService
    repo = MemoryRepository(tmp_path / "fk-task.db")
    await repo.open()

    # Create parent session
    await repo.db.execute(
        "INSERT OR IGNORE INTO sessions(session_id, title, start_time) VALUES (?, ?, datetime('now'));",
        ("s1", "test session"))
    entity_id = await repo.add_entity("test-agent", "agent")

    service = TaskService(repository=repo)
    start = await service.start_task(session_id="s1", entity_id=entity_id, task_type="coding", title="test task")
    assert start.status == "running"
    await repo.close()


@pytest.mark.asyncio
async def test_lesson_memory_fk_parent_exists(tmp_path: Path) -> None:
    """lesson_memories.memory_id FK must reference existing memory."""
    repo = MemoryRepository(tmp_path / "fk-lesson.db")
    await repo.open()

    # Create parent memory with all required columns
    import hashlib
    content = "Lesson: always test before deploy"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    checksum = content_hash
    await repo.db.execute(
        "INSERT OR IGNORE INTO memories(id,memory_type,content,content_hash,importance_score,confidence_score,active_state,checksum,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("lesson-parent-1", "LESSON", content, content_hash, 0.9, 0.9, "active", checksum))

    # Insert lesson memory — FK should succeed
    await repo.db.execute(
        "INSERT OR IGNORE INTO lesson_memories(id,memory_id,lesson_text,policy_type,severity,trigger_patterns_json,evidence_count,confidence_score,active_state,metadata_json) VALUES (?,?,?,?,?,?,?,?,'active','{}')",
        ("lesson-1", "lesson-parent-1", "Always test", "warn", 0.7, '["deploy"]', 3, 0.85))

    row = await repo.db.fetchone("SELECT id FROM lesson_memories WHERE id = ?;", ("lesson-1",))
    assert row, "lesson memory not found — FK insert may have failed"
    await repo.close()
