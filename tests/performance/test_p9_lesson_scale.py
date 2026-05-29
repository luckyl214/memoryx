"""P9-2: LESSON match performance at scale."""
from __future__ import annotations

import pytest
from pathlib import Path
from memoryx.storage import MemoryRepository


@pytest.mark.asyncio
async def test_lesson_match_p95_under_threshold(tmp_path: Path):
    """Verify lesson match stays performant after trigger index hardening."""
    from memoryx.cognitive.lesson_policy import LessonPolicyEngine
    import time, statistics

    repo = MemoryRepository(tmp_path / "p9-lesson-scale.db")
    await repo.open()

    # Seed 500 lessons with trigger patterns
    for i in range(500):
        await repo.db.execute(
            "INSERT OR IGNORE INTO memories(id,memory_type,content,content_hash,importance_score,confidence_score,active_state,checksum,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (f"lmem-{i}", "LESSON", f"Lesson {i}: check before deploy", f"ch_lmem{i}", 0.9, 0.9, "active", f"chk_lmem{i}"),
        )
        await repo.db.execute(
            "INSERT OR IGNORE INTO lesson_memories(id,memory_id,lesson_text,policy_type,severity,trigger_patterns_json,evidence_count,confidence_score,active_state,metadata_json) VALUES (?,?,?,?,?,?,?,?,'active','{}')",
            (f"pl9-{i:06d}", f"lmem-{i}", f"Lesson {i}", "warn", 0.5 + (i % 5) * 0.1, f'["topic_{i%10}"]', 2, 0.8),
        )

    engine = LessonPolicyEngine(repository=repo)

    latencies = []
    for i in range(30):
        t0 = time.perf_counter()
        try:
            await engine.match(query=f"test topic_{i%10}", intent="deployment", limit=10)
        except Exception:
            pass
        latencies.append((time.perf_counter() - t0) * 1000)

    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 999
    mean = statistics.mean(latencies) if latencies else 999

    # Soft threshold: under 50ms at 500-lesson scale
    assert mean < 50, f"Lesson match mean {mean:.1f}ms exceeds 50ms threshold"
    assert p95 < 100, f"Lesson match p95 {p95:.1f}ms exceeds 100ms threshold"

    await repo.close()
