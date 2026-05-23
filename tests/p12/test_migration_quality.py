from __future__ import annotations

from pathlib import Path


def test_p12_migration_removes_placeholder_index_and_adds_llm_safety():
    path = Path("db/migrations/021_hermes_perfection.sql")
    text = path.read_text(encoding="utf-8")
    assert "DROP INDEX IF EXISTS idx_taYOUR_API_KEY_HERE" in text
    assert "idx_task_durations_entity_time" in text
    assert "llm_safety_events" in text
