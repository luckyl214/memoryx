from __future__ import annotations

from pathlib import Path

from memoryx.governance import ResourceGovernanceEngine, ResourceLimits, RuntimeResourceSnapshot


def test_resource_governance_recommends_worker_scaling_down_under_memory_pressure(tmp_path: Path) -> None:
    engine = ResourceGovernanceEngine(
        limits=ResourceLimits(max_workers=4, min_workers=1, max_memory_ratio=0.75),
    )
    snapshot = RuntimeResourceSnapshot(
        workers=4,
        queue_depth=10,
        queue_size=100,
        memory_used_bytes=850,
        memory_total_bytes=1000,
        cpu_percent=35.0,
        disk_used_bytes=100,
        disk_limit_bytes=1000,
    )

    decision = engine.evaluate(snapshot)

    assert decision.worker_target == 2
    assert "memory_pressure" in decision.throttle_reasons
    assert decision.embedding_batch_size == 4


def test_resource_governance_scales_up_when_queue_is_hot_and_resources_safe() -> None:
    engine = ResourceGovernanceEngine(
        limits=ResourceLimits(max_workers=4, min_workers=1, queue_hot_ratio=0.8),
    )
    snapshot = RuntimeResourceSnapshot(
        workers=1,
        queue_depth=90,
        queue_size=100,
        memory_used_bytes=300,
        memory_total_bytes=1000,
        cpu_percent=30.0,
        disk_used_bytes=200,
        disk_limit_bytes=1000,
    )

    decision = engine.evaluate(snapshot)

    assert decision.worker_target == 2
    assert decision.throttle_reasons == []
    assert decision.retrieval_rate_limit_per_minute == 60


def test_resource_governance_enforces_token_and_disk_limits(tmp_path: Path) -> None:
    engine = ResourceGovernanceEngine(
        limits=ResourceLimits(max_context_tokens=1200, disk_warning_ratio=0.8),
    )
    snapshot = RuntimeResourceSnapshot(
        workers=2,
        queue_depth=8,
        queue_size=100,
        memory_used_bytes=400,
        memory_total_bytes=1000,
        cpu_percent=40.0,
        disk_used_bytes=900,
        disk_limit_bytes=1000,
        requested_context_tokens=4000,
    )

    decision = engine.evaluate(snapshot)

    assert decision.context_token_budget == 1200
    assert "disk_growth" in decision.throttle_reasons
    assert decision.retrieval_rate_limit_per_minute == 30


def test_resource_governance_can_snapshot_disk_usage(tmp_path: Path) -> None:
    data_file = tmp_path / "cache.bin"
    data_file.write_bytes(b"x" * 128)
    engine = ResourceGovernanceEngine()

    snapshot = engine.snapshot(
        workers=2,
        queue_depth=3,
        queue_size=16,
        memory_used_bytes=256,
        memory_total_bytes=1024,
        cpu_percent=12.5,
        disk_path=tmp_path,
        disk_limit_bytes=1024,
    )

    assert snapshot.disk_used_bytes >= 128
    assert snapshot.disk_limit_bytes == 1024
