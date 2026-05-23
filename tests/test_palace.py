from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.palace import PalaceEngine, PalaceNavigator
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_palace_wing_and_room_creation(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "palace-demo.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    wing = await engine.ensure_wing("project-memoryx", "Cognitive Memory OS")
    assert wing.name == "project-memoryx"
    assert wing.description == "Cognitive Memory OS"

    wing2 = await engine.ensure_wing("project-memoryx")
    assert wing2.wing_id == wing.wing_id

    room = await engine.ensure_room(wing.wing_id, "phase-28", "Meta-Cognitive Reflection")
    assert room.name == "phase-28"
    assert room.description == "Meta-Cognitive Reflection"
    await repo.close()


@pytest.mark.asyncio
async def test_palace_drawer_add_and_retrieve(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "palace-drawers.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    wing = await engine.ensure_wing("test")
    room = await engine.ensure_room(wing.wing_id, "sprint-1")
    drawer = await engine.add_drawer(room.room_id, "deploy failed due to timeout", source="conversation")

    drawers = await engine.list_drawers(room.room_id)
    assert len(drawers) == 1
    assert drawers[0].content == "deploy failed due to timeout"
    assert drawers[0].source == "conversation"

    fetched = await engine.get_drawer(drawer.drawer_id)
    assert fetched is not None
    assert fetched.content == "deploy failed due to timeout"
    await repo.close()


@pytest.mark.asyncio
async def test_palace_search_within_wing(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "palace-search.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    wing = await engine.ensure_wing("alpha")
    room = await engine.ensure_room(wing.wing_id, "s1")
    await engine.add_drawer(room.room_id, "user prefers async python")
    await engine.add_drawer(room.room_id, "deployment failed")
    room2 = await engine.ensure_room(wing.wing_id, "s2")
    await engine.add_drawer(room2.room_id, "async queue worker")

    results = await engine.search_wing("alpha", "async")
    assert len(results) >= 2
    assert any("async python" in r.content for r in results)
    assert any("async queue" in r.content for r in results)
    await repo.close()


@pytest.mark.asyncio
async def test_palace_traverse_tunnels(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "palace-tunnels.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)

    w1 = await engine.ensure_wing("wing-a")
    w2 = await engine.ensure_wing("wing-b")
    w3 = await engine.ensure_wing("wing-c")
    await engine.add_tunnel(w1.wing_id, w2.wing_id)
    await engine.add_tunnel(w2.wing_id, w3.wing_id)

    results = await engine.traverse("wing-a", depth=3)
    names = {r["name"] for r in results}
    assert "wing-a" in names
    assert "wing-b" in names
    assert "wing-c" in names
    await repo.close()


@pytest.mark.asyncio
async def test_palace_navigator_walk(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "palace-walk.db")
    await repo.open()
    engine = PalaceEngine(repository=repo)
    nav = PalaceNavigator(engine)

    wing = await engine.ensure_wing("docs")
    room = await engine.ensure_room(wing.wing_id, "architecture")
    await engine.add_drawer(room.room_id, "event-driven architecture")

    lines = await nav.walk_to("docs", "architecture")
    assert len(lines) >= 1
    assert "event-driven architecture" in lines[0]

    overview = await nav.walk_to("docs")
    assert any("Wing: docs" in line for line in overview)
    await repo.close()
