from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.context import ContextBundle
from memoryx.observability import MemoryObservabilityEngine
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_observability_reads_access_logs(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "observability-access.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="m1", memory_type="FACT", content="User prefers async Python"))
    await repo.record_access("m1")

    engine = MemoryObservabilityEngine(repository=repo)
    logs = await engine.memory_access_logs(memory_id="m1")

    assert len(logs) == 1
    assert logs[0]["memory_id"] == "m1"
    assert logs[0]["access_type"] == "read"
    await repo.close()


@pytest.mark.asyncio
async def test_observability_reads_audit_logs_and_lineage(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "observability-audit.db")
    await repo.open()
    await repo.store_memory(MemoryRecord(id="m2", memory_type="PROJECT", content="Initial project state"))
    await repo.store_memory(MemoryRecord(id="m2", memory_type="PROJECT", content="Updated project state"))
    await repo.append_audit("custom_action", "m2", {"detail": "ok"})

    engine = MemoryObservabilityEngine(repository=repo)
    audits = await engine.audit_logs(subject_id="m2")
    lineage = await engine.memory_lineage(memory_id="m2")

    assert len(audits) >= 3
    # P0 schema: audit_logs.entity_id, not subject_id
    assert audits[-1]["entity_id"] == "m2"
    assert len(lineage["versions"]) >= 2
    assert len(lineage["audits"]) >= 3
    await repo.close()


@pytest.mark.asyncio
async def test_observability_builds_retrieval_trace() -> None:
    engine = MemoryObservabilityEngine(repository=None)

    trace = engine.retrieval_trace(
        query="async python",
        route="preference",
        intent="preference",
        results=[
            {
                "memory_id": "m3",
                "final_score": 1.8,
                "explanation": "semantic=0.90, keyword=0.80, importance=0.70, intent=preference",
            }
        ],
    )

    assert trace["query"] == "async python"
    assert trace["route"] == "preference"
    assert trace["result_count"] == 1
    assert trace["results"][0]["memory_id"] == "m3"


@pytest.mark.asyncio
async def test_observability_builds_context_trace() -> None:
    engine = MemoryObservabilityEngine(repository=None)
    bundle = ContextBundle(
        rendered="joined context",
        token_count=128,
        truncated=False,
        used_summary_fallback=True,
        sections={"User Preferences": ["pref A"], "Project Context": ["ctx B"]},
    )

    trace = engine.context_trace(bundle)

    assert trace["token_count"] == 128
    assert trace["used_summary_fallback"] is True
    assert trace["sections"]["User Preferences"] == 1
