from __future__ import annotations

import pytest

from memoryx.context_reasoning import ContextReasoningEngine
from memoryx.retrieval import RetrievalResult


def _candidate(
    memory_id: str,
    memory_type: str,
    content: str,
    *,
    final_score: float,
    scope: str = "user",
) -> RetrievalResult:
    return RetrievalResult(
        memory_id=memory_id,
        content=content,
        memory_type=memory_type,
        scope=scope,
        semantic_score=final_score,
        keyword_score=0.0,
        temporal_score=0.0,
        entity_score=0.0,
        importance_score=0.0,
        episodic_score=0.0,
        final_score=final_score,
        explanation="",
    )


@pytest.mark.asyncio
async def test_reasoning_engine_scores_usefulness_and_reranks() -> None:
    engine = ContextReasoningEngine()
    candidates = [
        _candidate("m1", "PROJECT", "Project uses async Python and lightweight infra", final_score=0.61),
        _candidate("m2", "PREFERENCE", "User likes tomatoes", final_score=0.95),
        _candidate("m3", "TASK", "Current debugging task involves queue timeout and worker backpressure", final_score=0.58),
    ]

    ranked = await engine.rerank(
        query="debug queue timeout in worker",
        intent="debugging",
        candidates=candidates,
    )

    assert [item.memory_id for item in ranked][:2] == ["m3", "m1"]
    assert "usefulness=" in ranked[0].explanation


@pytest.mark.asyncio
async def test_reasoning_engine_builds_project_narrative_and_causal_chain() -> None:
    engine = ContextReasoningEngine()
    candidates = [
        _candidate("m1", "PROJECT", "Project goal is stable long-running memory runtime", final_score=0.7),
        _candidate("m2", "TASK", "Worker queue overflow caused delayed processing", final_score=0.68),
        _candidate("m3", "OBSERVATION", "Backpressure threshold was too high for 2C4G VPS", final_score=0.65),
    ]

    explanation = await engine.explain_context(
        query="why did the worker backlog happen",
        intent="debugging",
        candidates=candidates,
    )

    assert "stable long-running memory runtime" in explanation["project_narrative"]
    assert len(explanation["causal_chain"]) >= 2
    assert any("overflow" in step.lower() for step in explanation["causal_chain"])


@pytest.mark.asyncio
async def test_reasoning_engine_detects_conflicting_context() -> None:
    engine = ContextReasoningEngine()
    candidates = [
        _candidate("m1", "PREFERENCE", "User prefers ORM-heavy frameworks", final_score=0.8),
        _candidate("m2", "PREFERENCE", "User prefers lightweight infra and no ORM", final_score=0.79),
    ]

    result = await engine.analyze_conflicts(
        query="what stack should we use",
        intent="coding",
        candidates=candidates,
    )

    assert result["has_conflict"] is True
    assert result["conflict_pairs"][0]["left"] == "m1"


@pytest.mark.asyncio
async def test_reasoning_engine_filters_low_usefulness_memories() -> None:
    engine = ContextReasoningEngine()
    candidates = [
        _candidate("m1", "PREFERENCE", "User likes blue color", final_score=0.85),
        _candidate("m2", "TASK", "Current coding task is implementing context reasoning engine", final_score=0.6),
    ]

    filtered = await engine.select_useful(
        query="implement context reasoning engine",
        intent="coding",
        candidates=candidates,
        threshold=0.4,
    )

    assert [item.memory_id for item in filtered] == ["m2"]
