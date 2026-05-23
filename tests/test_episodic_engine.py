from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.episodic import EpisodicMemoryEngine
from memoryx.storage import MemoryRepository


@pytest.mark.asyncio
async def test_episodic_engine_stores_session_episode(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "episodic.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)

    episodic_id = await engine.record_episode(
        session_id="s1",
        title="Debugging API timeout",
        events=["Observed timeout", "Retried request", "Applied backoff", "Recovered service"],
        importance_score=0.85,
    )

    episodes = await engine.session_timeline("s1")
    assert episodic_id
    assert len(episodes) == 1
    assert episodes[0]["title"] == "Debugging API timeout"
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_engine_builds_event_chain_summary(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "episodic-summary.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)

    summary = engine.summarize_events([
        "Deployment started",
        "Health check failed",
        "Rolled back release",
        "Service restored",
    ])

    assert "Deployment started" in summary
    assert "Service restored" in summary
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_engine_retrieves_high_importance_episodes(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "episodic-importance.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)

    await engine.record_episode("s2", "Minor issue", ["small warning"], importance_score=0.2)
    await engine.record_episode("s2", "Major incident", ["service down", "mitigated"], importance_score=0.95)

    episodes = await engine.top_episodes(limit=1)

    assert len(episodes) == 1
    assert episodes[0]["title"] == "Major incident"
    await repo.close()


@pytest.mark.asyncio
async def test_episodic_engine_queries_related_episodes(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "episodic-query.db")
    await repo.open()
    engine = EpisodicMemoryEngine(repository=repo)

    await engine.record_episode("s3", "Deployment incident", ["deploy failed", "rollback complete"], importance_score=0.9)
    await engine.record_episode("s4", "Debugging cache", ["cache miss", "fixed keying bug"], importance_score=0.7)

    matches = await engine.search("rollback")

    assert len(matches) == 1
    assert matches[0]["title"] == "Deployment incident"
    await repo.close()
