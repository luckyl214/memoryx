"""P4: GraphRetriever + TemporalScorer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.retrieval.graph_retriever import GraphRetriever
from memoryx.storage import MemoryRecord, MemoryRepository
from memoryx.temporal_scorer import TemporalScorer, TemporalQueryIntent


# ── GraphRetriever ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_retriever_resolves_entities(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "graph_test.db")
    await repo.open()
    await repo.add_entity("Hermes", entity_type="agent")

    gr = GraphRetriever(repository=repo)
    ids = await gr._resolve_entities(["hermes"])
    assert len(ids) == 1
    await repo.close()


@pytest.mark.asyncio
async def test_graph_empty_on_unknown_entity(tmp_path: Path):
    repo = MemoryRepository(tmp_path / "graph_empty.db")
    await repo.open()
    gr = GraphRetriever(repository=repo)
    results = await gr.retrieve(["nonexistent"])
    assert results == []
    await repo.close()


# ── TemporalScorer ──────────────────────────────────────────────

def test_temporal_classify_past():
    ts = TemporalScorer()
    intent = ts.classify_intent("what did I do yesterday")
    assert intent.intent == "past"


def test_temporal_classify_future():
    ts = TemporalScorer()
    intent = ts.classify_intent("what is the plan for next week")
    assert intent.intent == "future"


def test_temporal_classify_current():
    ts = TemporalScorer()
    intent = ts.classify_intent("how does this work")
    assert intent.intent == "current"


@pytest.mark.asyncio
async def test_temporal_score_expired_memory():
    ts = TemporalScorer()
    memory = {
        "valid_from": "2020-01-01T00:00:00",
        "valid_to": "2020-12-31T00:00:00",
    }
    score = await ts.score(memory, TemporalQueryIntent(intent="current"))
    assert score < 0.3  # heavily decayed + expired penalty


@pytest.mark.asyncio
async def test_temporal_score_recent_memory():
    ts = TemporalScorer()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    yesterday = now.replace(day=now.day - 1 if now.day > 1 else 28).isoformat()
    memory = {"valid_from": yesterday, "valid_to": None}
    score = await ts.score(memory, TemporalQueryIntent(intent="current"))
    assert score > 0.8  # recent memory, high score
