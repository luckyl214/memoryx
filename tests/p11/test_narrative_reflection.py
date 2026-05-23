from __future__ import annotations

import pytest
from memoryx.cognitive.narrative_reflection import NarrativeReflectionEngine


class FakeDB:
    def __init__(self):
        self.persisted = []

    async def fetchall(self, sql, params=()):
        if "FROM task_durations" in sql:
            return [{"id": "td1", "task_id": "read-three-body", "duration_seconds": 9000, "entity_id": "book-3body"}]
        if "FROM opinion_shifts" in sql:
            return [{"id": "os1", "delta": -0.6, "before_summary": "very positive", "after_summary": "neutral"}]
        if "FROM lesson_memories" in sql:
            return [{"id": "l1", "lesson_text": "Do dry-run before production deploy.", "severity": 0.9}]
        if "FROM claim_verification_runs" in sql:
            return [{"id": "c1", "risk_score": 0.4, "action": "warn"}]
        return []

    async def execute(self, sql, params=()):
        self.persisted.append((sql, params))


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


@pytest.mark.asyncio
async def test_narrative_reflection_summarizes_time_opinion_lessons_and_claims():
    repo = FakeRepo()
    engine = NarrativeReflectionEngine(repository=repo)
    reflection = await engine.generate(window_start="2025-01-01T00:00:00Z", window_end="2025-12-31T23:59:59Z", entity_id="book-3body", reflection_type="entity", store=True)
    assert "任务耗时" in reflection.summary
    assert "观点变化" in reflection.summary
    assert "学习教训" in reflection.summary
    assert "事实校验" in reflection.summary
    assert reflection.metrics["total_duration_seconds"] == 9000
    assert repo.db.persisted
