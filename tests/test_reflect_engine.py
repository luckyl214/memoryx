from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.reflect import ReflectEngine
from memoryx.storage import MemoryRecord, MemoryRepository


class DummyVectorStore:
    async def search(self, query_vector: list[float], limit: int = 10) -> list[dict]:
        return [
            {"memory_id": "m1", "score": 0.95},
            {"memory_id": "m2", "score": 0.85},
        ]


class DummyRetrievalEngine:
    def __init__(self, repository) -> None:
        self.repository = repository

    async def retrieve(self, *, query: str, query_vector: list[float], limit: int = 10, **kwargs):
        from memoryx.retrieval import RetrievalResult
        return [
            RetrievalResult(
                memory_id="m1",
                content="User prefers async Python over sync",
                memory_type="PREFERENCE",
                scope="user",
                semantic_score=0.9,
                keyword_score=0.8,
                temporal_score=0.5,
                entity_score=0.0,
                importance_score=0.85,
                episodic_score=0.0,
                final_score=0.92,
                explanation="semantic=0.90 keyword=0.80 importance=0.85",
            ),
            RetrievalResult(
                memory_id="m2",
                content="User dislikes ORM, prefers lightweight infrastructure",
                memory_type="PREFERENCE",
                scope="user",
                semantic_score=0.85,
                keyword_score=0.7,
                temporal_score=0.4,
                entity_score=0.0,
                importance_score=0.8,
                episodic_score=0.0,
                final_score=0.88,
                explanation="semantic=0.85 keyword=0.70 importance=0.80",
            ),
        ]


@pytest.mark.asyncio
async def test_reflect_returns_synthesis_without_llm() -> None:
    """没有 LLM 时，reflect 退回返回原始记忆。"""
    retrieval = DummyRetrievalEngine(repository=None)
    engine = ReflectEngine(retrieval_engine=retrieval)
    result = await engine.reflect(query="what does the user like?", query_vector=[1.0, 0.0, 0.0, 0.0])

    assert result["query"] == "what does the user like?"
    assert result["count"] == 2
    assert result["synthesis"] == ""
    assert result["memories"][0]["content"] == "User prefers async Python over sync"
    assert result["memories"][1]["content"] == "User dislikes ORM, prefers lightweight infrastructure"


@pytest.mark.asyncio
async def test_reflect_calls_llm_synthesize_when_provided() -> None:
    """提供 LLM 合成函数时，返回合成答案。"""
    retrieval = DummyRetrievalEngine(repository=None)

    def fake_synthesize(query: str, memories) -> str:
        assert "async Python" in query or "like" in query
        return "Based on your memories, you prefer async Python and lightweight infrastructure without ORM."

    engine = ReflectEngine(retrieval_engine=retrieval, llm_synthesize=fake_synthesize)
    result = await engine.reflect(query="what do I like?", query_vector=[1.0, 0.0, 0.0, 0.0])

    assert "async Python" in result["synthesis"]
    assert "lightweight infrastructure" in result["synthesis"]
    assert result["count"] == 2


def test_build_synthesis_prompt() -> None:
    """合成 prompt 包含查询和检索结果。"""
    prompt = ReflectEngine.build_synthesis_prompt(
        query="test query",
        memories=[
            {"content": "memory one", "memory_type": "FACT", "scope": "global", "final_score": 0.95},
            {"content": "memory two", "memory_type": "PREFERENCE", "scope": "user", "final_score": 0.85},
        ],
    )

    assert "test query" in prompt
    assert "memory one" in prompt
    assert "memory two" in prompt
    assert "FACT" in prompt
    assert "PREFERENCE" in prompt
