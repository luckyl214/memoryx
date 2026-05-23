from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class ResourceLimits:
    max_workers: int = 4
    min_workers: int = 1
    max_memory_ratio: float = 0.75
    queue_hot_ratio: float = 0.8
    max_context_tokens: int = 4096
    disk_warning_ratio: float = 0.85
    max_retrieval_rate_per_minute: int = 60


@dataclass(slots=True)
class RuntimeResourceSnapshot:
    workers: int
    queue_depth: int
    queue_size: int
    memory_used_bytes: int
    memory_total_bytes: int
    cpu_percent: float
    disk_used_bytes: int
    disk_limit_bytes: int
    requested_context_tokens: int = 0


@dataclass(slots=True)
class ResourceGovernanceDecision:
    worker_target: int
    embedding_batch_size: int
    retrieval_rate_limit_per_minute: int
    context_token_budget: int
    throttle_reasons: list[str]


class ResourceGovernanceEngine:
    def __init__(self, *, limits: ResourceLimits | None = None) -> None:
        self.limits = limits or ResourceLimits()

    def evaluate(self, snapshot: RuntimeResourceSnapshot) -> ResourceGovernanceDecision:
        throttle_reasons: list[str] = []
        worker_target = snapshot.workers
        embedding_batch_size = 16
        retrieval_rate_limit = self.limits.max_retrieval_rate_per_minute
        context_budget = self.limits.max_context_tokens

        memory_ratio = self._ratio(snapshot.memory_used_bytes, snapshot.memory_total_bytes)
        queue_ratio = self._ratio(snapshot.queue_depth, snapshot.queue_size)
        disk_ratio = self._ratio(snapshot.disk_used_bytes, snapshot.disk_limit_bytes)

        if memory_ratio >= self.limits.max_memory_ratio:
            throttle_reasons.append("memory_pressure")
            worker_target = max(self.limits.min_workers, max(1, snapshot.workers // 2))
            embedding_batch_size = 4
            retrieval_rate_limit = max(10, retrieval_rate_limit // 2)
        elif queue_ratio >= self.limits.queue_hot_ratio:
            worker_target = min(self.limits.max_workers, snapshot.workers + 1)
            retrieval_rate_limit = retrieval_rate_limit
        else:
            worker_target = max(self.limits.min_workers, min(snapshot.workers, self.limits.max_workers))

        if disk_ratio >= self.limits.disk_warning_ratio:
            throttle_reasons.append("disk_growth")
            retrieval_rate_limit = max(15, retrieval_rate_limit // 2)

        if snapshot.cpu_percent >= 85.0:
            throttle_reasons.append("cpu_pressure")
            worker_target = max(self.limits.min_workers, worker_target - 1)

        if snapshot.requested_context_tokens:
            context_budget = min(self.limits.max_context_tokens, snapshot.requested_context_tokens)

        return ResourceGovernanceDecision(
            worker_target=worker_target,
            embedding_batch_size=embedding_batch_size,
            retrieval_rate_limit_per_minute=retrieval_rate_limit,
            context_token_budget=context_budget,
            throttle_reasons=self._unique(throttle_reasons),
        )

    def snapshot(
        self,
        *,
        workers: int,
        queue_depth: int,
        queue_size: int,
        memory_used_bytes: int,
        memory_total_bytes: int,
        cpu_percent: float,
        disk_path: Optional[Path] = None,
        disk_limit_bytes: int,
        requested_context_tokens: int = 0,
    ) -> RuntimeResourceSnapshot:
        disk_used_bytes = self._disk_usage(disk_path) if disk_path is not None else 0
        return RuntimeResourceSnapshot(
            workers=workers,
            queue_depth=queue_depth,
            queue_size=queue_size,
            memory_used_bytes=memory_used_bytes,
            memory_total_bytes=memory_total_bytes,
            cpu_percent=cpu_percent,
            disk_used_bytes=disk_used_bytes,
            disk_limit_bytes=disk_limit_bytes,
            requested_context_tokens=requested_context_tokens,
        )

    def _ratio(self, used: int | float, total: int | float) -> float:
        if total <= 0:
            return 0.0
        return float(used) / float(total)

    def _disk_usage(self, disk_path: Path) -> int:
        total = 0
        if not disk_path.exists():
            return 0
        for path in disk_path.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered
