from __future__ import annotations

import pytest

from memoryx.cognitive.feedback import FeedbackLearningEngine
from memoryx.cognitive.models import FeedbackEvent
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_negative_feedback_propagates_and_creates_lesson(tmp_path):
    repo = MemoryRepository(tmp_path / "learning.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="a", memory_type="FACT", content="deployment used --force in production and caused rollback", confidence_score=0.9, importance_score=0.9, metadata_json='{"tags":["deployment"],"entities":["production"]}'))
    await repo.store_memory(MemoryRecord(id="b", memory_type="FACT", content="production deploy used --force and failed", confidence_score=0.9, importance_score=0.8, metadata_json='{"tags":["deployment"],"entities":["production"]}'))
    await repo.store_memory(MemoryRecord(id="c", memory_type="FACT", content="coffee preference", confidence_score=0.9, importance_score=0.3))

    engine = FeedbackLearningEngine(repository=repo)
    result = await engine.apply_feedback(FeedbackEvent(memory_id="a", positive=False, reason="dangerous deploy flag"), dry_run=False)

    assert result.affected
    assert result.lesson_created is not None
    lesson = await repo.get_memory(result.lesson_created)
    assert lesson and lesson["memory_type"] == "LESSON"
    unrelated = await repo.get_memory("c")
    assert unrelated["confidence_score"] == 0.9
    await repo.close()
