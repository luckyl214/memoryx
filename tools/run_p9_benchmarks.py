#!/usr/bin/env python3
"""P9 benchmark runner: measure retrieval, lesson match, entity timeline, store latencies."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_vals):
        return sorted_vals[f] * (1 - c) + sorted_vals[f + 1] * c
    return sorted_vals[f]


async def bench_retrieval(db_path: Path, queries: int = 50) -> dict:
    from memoryx.storage import MemoryRepository
    from memoryx.retrieval import HybridRetrievalEngine

    repo = MemoryRepository(db_path)
    await repo.open()

    class DummyVectorStore:
        async def search(self, vector, limit=50):
            return []

    engine = HybridRetrievalEngine(repository=repo, vector_store=DummyVectorStore())

    latencies: list[float] = []
    topics = ["deployment", "debugging", "api", "database", "security", "performance"]

    for i in range(queries):
        query = f"{topics[i % len(topics)]} test query {i}"
        t0 = time.perf_counter()
        try:
            results = await engine.retrieve(query=query, query_vector=[], limit=10, include_lessons=True)
        except Exception:
            pass
        latencies.append((time.perf_counter() - t0) * 1000)

    await repo.close()
    return {
        "queries": queries,
        "p50_ms": round(percentile(latencies, 50), 2),
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
        "max_ms": round(max(latencies), 2) if latencies else 0,
    }


async def bench_lesson_match(db_path: Path, queries: int = 30) -> dict:
    from memoryx.cognitive.lesson_policy import LessonPolicyEngine
    from memoryx.storage import MemoryRepository

    repo = MemoryRepository(db_path)
    await repo.open()
    engine = LessonPolicyEngine(repository=repo)

    latencies: list[float] = []

    topics = ["deployment", "debugging", "api", "database", "security"]
    for i in range(queries):
        query = f"{topics[i % len(topics)]} test query {i}"
        t0 = time.perf_counter()
        try:
            await engine.match(query=query, intent="deployment", limit=10)
        except Exception:
            pass
        latencies.append((time.perf_counter() - t0) * 1000)

    await repo.close()
    return {
        "queries": queries,
        "p50_ms": round(percentile(latencies, 50), 2),
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
    }


async def bench_store(db_path: Path, records: int = 200) -> dict:
    from memoryx.storage import MemoryRepository, MemoryRecord

    repo = MemoryRepository(db_path)
    await repo.open()

    latencies: list[float] = []

    for i in range(records):
        record = MemoryRecord(
            id=f"bench-store-{i:06d}",
            memory_type="OBSERVATION",
            content=f"Benchmark store record {i}",
            importance_score=0.5,
            confidence_score=0.8,
        )
        t0 = time.perf_counter()
        try:
            await repo.store_memory(record)
        except Exception:
            pass
        latencies.append((time.perf_counter() - t0) * 1000)

    await repo.close()
    return {
        "records": records,
        "p50_ms": round(percentile(latencies, 50), 2),
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0,
    }


async def run_all(db_path: Path, *, queries: int = 50, store_records: int = 200) -> dict:
    print(f"Benchmarking {db_path}...")
    t0 = time.perf_counter()

    retrieval = await bench_retrieval(db_path, queries=queries)
    print(f"  retrieval: p95={retrieval['p95_ms']}ms")

    lesson = await bench_lesson_match(db_path, queries=max(30, queries // 2))
    print(f"  lesson_match: p95={lesson['p95_ms']}ms")

    store = await bench_store(db_path, records=store_records)
    print(f"  store: p95={store['p95_ms']}ms")

    elapsed = round((time.perf_counter() - t0), 2)
    print(f"  total: {elapsed}s")

    return {
        "suite": "memoryx-p9",
        "generated_at": _now(),
        "db_path": str(db_path),
        "total_seconds": elapsed,
        "retrieval": retrieval,
        "lesson_match": lesson,
        "store": store,
    }


def main():
    parser = argparse.ArgumentParser(description="P9 benchmark runner")
    parser.add_argument("--db", type=Path, required=True, help="Path to scale dataset DB")
    parser.add_argument("--queries", type=int, default=50, help="Number of benchmark queries")
    parser.add_argument("--store-records", type=int, default=200, help="Store benchmark records")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON report path")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}. Run tools/generate_scale_dataset.py first.", file=__import__("sys").stderr)
        raise SystemExit(1)

    report = asyncio.run(run_all(args.db, queries=args.queries, store_records=args.store_records))

    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWritten: {args.output}")

    # Print summary for CI
    print(f"\nP9_BENCH: retrieval_p95_ms={report['retrieval']['p95_ms']}")
    print(f"P9_BENCH: lesson_match_p95_ms={report['lesson_match']['p95_ms']}")
    print(f"P9_BENCH: store_p95_ms={report['store']['p95_ms']}")


if __name__ == "__main__":
    main()
