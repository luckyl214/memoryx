from __future__ import annotations


class HealthMonitor:
    def __init__(self) -> None:
        self.event_throughput = 0
        self.worker_latency_ms = 0.0
        self.drop_rate = 0

    def record_event(self) -> None:
        self.event_throughput += 1

    def record_latency(self, elapsed_ms: float) -> None:
        self.worker_latency_ms = max(self.worker_latency_ms, elapsed_ms)

    def record_drop(self) -> None:
        self.drop_rate += 1

    def metrics(self, queue_depth: int = 0, queue_maxsize: int = 0, worker_count: int = 0, **extra) -> dict:
        queue_pressure = 0.0
        if queue_maxsize > 0:
            queue_pressure = queue_depth / queue_maxsize
        return {
            "event_throughput": self.event_throughput,
            "worker_latency_ms": self.worker_latency_ms,
            "drop_rate": self.drop_rate,
            "queue_depth": queue_depth,
            "queue_size": queue_maxsize,
            "queue_pressure": queue_pressure,
            "worker_count": worker_count,
            **extra,
        }
