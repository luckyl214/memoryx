from __future__ import annotations

import pytest

from memoryx.retrieval.observed import instrument_retrieval_engine


class FakeRetrievalEngine:
    def __init__(self):
        self.calls = []

    async def _semantic_candidates(self, *args, **kwargs):
        self.calls.append("semantic")
        return []

    async def _merge_lesson_candidates(self, results, *args, **kwargs):
        self.calls.append("lesson")
        return results

    async def retrieve(self, *args, **kwargs):
        candidates = await self._semantic_candidates(*args, **kwargs)
        return await self._merge_lesson_candidates(candidates, *args, **kwargs)


@pytest.mark.asyncio
async def test_instrument_retrieval_engine_wraps_total_and_stage_methods():
    engine = FakeRetrievalEngine()
    observed = instrument_retrieval_engine(engine)

    result = await observed.retrieve(query="deploy --force", query_vector=[])

    assert result == []
    assert engine.calls == ["semantic", "lesson"]
