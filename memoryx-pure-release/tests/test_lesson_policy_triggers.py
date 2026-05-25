from __future__ import annotations

import pytest

from memoryx.cognitive.lesson_policy import LessonPolicyEngine


class FakeDB:
    def __init__(self):
        self.lesson_rows = [
            {
                "memory_id": "lesson-1-mem",
                "content": "Do not use --force in production deployments.",
                "memory_type": "LESSON",
                "importance_score": 0.9,
                "confidence_score": 0.9,
                "scope": "global",
                "session_id": None,
                "lesson_id": "lesson-1",
                "lesson_text": "Do not use --force in production deployments.",
                "policy_type": "warn",
                "severity": 0.95,
                "trigger_intents_json": '["deployment"]',
                "trigger_patterns_json": '["deploy", "production", "--force"]',
                "prohibited_patterns_json": '["--force"]',
                "recommended_action": "ask confirmation",
                "evidence_count": 2,
            }
        ]

    async def fetchone(self, sql, params=()):
        if "sqlite_master" in sql and "lesson_triggers" in sql:
            return {"name": "lesson_triggers"}
        return None

    async def fetchall(self, sql, params=()):
        if "FROM lesson_triggers" in sql:
            return [{"lesson_id": "lesson-1"}]
        if "FROM lesson_memories" in sql:
            return self.lesson_rows
        return []


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


@pytest.mark.asyncio
async def test_lesson_policy_uses_trigger_index_and_scores_match():
    engine = LessonPolicyEngine(repository=FakeRepo())

    matches = await engine.match(
        query="deploy production with --force",
        intent="deployment",
        include_global=True,
    )

    assert matches
    assert matches[0]["memory_id"] == "lesson-1-mem"
    assert matches[0]["lesson_match_score"] > 0.5
    assert "prohibited:--force" in matches[0]["lesson_match_reasons"]
