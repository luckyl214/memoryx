from __future__ import annotations

import pytest
from memoryx.cognitive.lesson_enforcement import LessonEnforcementPolicyEngine


class FakeDB:
    def __init__(self):
        self.events = []

    async def fetchall(self, sql, params=()):
        return [{
            "id": "lesson-1",
            "memory_id": "lesson-memory-1",
            "content": "Never deploy production with --force without dry-run and confirmation.",
            "lesson_text": "Never deploy production with --force without dry-run and confirmation.",
            "policy_type": "warn",
            "severity": 0.95,
            "recommended_action": "require_dry_run_and_confirmation",
            "trigger_patterns_json": '["deploy","production","--force"]',
            "prohibited_patterns_json": '["--force"]',
        }]

    async def execute(self, sql, params=()):
        self.events.append((sql, params))


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


@pytest.mark.asyncio
async def test_lesson_enforcement_requires_dry_run_for_force_deploy():
    repo = FakeRepo()
    engine = LessonEnforcementPolicyEngine(repository=repo)
    decision = await engine.evaluate_action(action_text="deploy production with --force", intent="deployment", session_id="s1", store=True)
    assert decision.decision == "require_dry_run"
    assert decision.matched_lessons
    assert repo.db.events
