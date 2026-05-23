from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.scene import Scene, SceneEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_scene_engine_clusters_memories(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "scene-cluster.db")
    await repo.open()
    base = "2026-05-22T10:00:00"
    for i, (mid, content, importance) in enumerate([
        ("s1", "deploy failed due to timeout", 0.9),
        ("s2", "rollback completed successfully", 0.8),
        ("s3", "user prefers async python", 0.7),
        ("s4", "user likes lightweight infra", 0.7),
    ]):
        record = MemoryRecord(memory_id=mid, memory_type="FACT", content=content, importance_score=importance)
        await repo.store_memory(record)

    engine = SceneEngine(repository=repo)
    scenes = await engine.build_scenes(time_window_minutes=1440)

    assert len(scenes) >= 1
    assert sum(len(s.memory_ids) for s in scenes) >= 4
    await repo.close()


@pytest.mark.asyncio
async def test_scene_export_markdown(tmp_path: Path) -> None:
    scene = Scene(scene_id="test-1", title="Test Scene", description="test description")
    scene.memory_ids = ["m1", "m2"]

    markdown = scene.to_markdown()
    assert "Test Scene" in markdown
    assert "m1" in markdown
    assert "m2" in markdown

    engine = SceneEngine(repository=None)  # type: ignore
    paths = await engine.export_markdown([scene], tmp_path / "scenes")

    assert len(paths) == 1
    assert Path(paths[0]).exists()
    assert "Test Scene" in Path(paths[0]).read_text()


def test_scene_description_heuristic() -> None:
    engine = SceneEngine(repository=None)  # type: ignore
    assert "debugging" in engine._describe_scene(["bug in worker", "error timeout"])
    assert "deployment" in engine._describe_scene(["deploy release v2"])
    assert "preference" in engine._describe_scene(["user prefers async"])
    assert engine._describe_scene(["general note"]) == ""
