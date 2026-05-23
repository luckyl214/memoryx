#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from memoryx.retrieval import HybridRetrievalEngine
from memoryx.storage import MemoryRecord, MemoryRepository


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/bench_retrieval.sqlite3"))
    parser.add_argument("--records", type=int, default=5000)
    parser.add_argument("--queries", type=int, default=100)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    repo = MemoryRepository(args.db)
    await repo.open()
    existing = await repo.db.fetchone("SELECT COUNT(*) AS cnt FROM memories;", ())
    if not existing or int(existing["cnt"]) < args.records:
        for i in range(args.records):
            await repo.store_memory(
                MemoryRecord(
                    id=f"bench-ret-{i}",
                    memory_type="FACT",
                    content=f"benchmark retrieval memory {i} about deployment debugging sqlite async lesson",
                    importance_score=0.5,
                    confidence_score=0.8,
                    scope="global",
                )
            )

    engine = HybridRetrievalEngine(repository=repo, vector_store=None)
    latencies: list[float] = []
    for _ in range(args.queries):
        start = time.perf_counter()
        await engine.retrieve(
            query="deployment debugging sqlite lesson",
            query_vector=[],
            limit=10,
            include_lessons=True,
            include_global=True,
        )
        latencies.append((time.perf_counter() - start) * 1000)

    await repo.close()
    latencies.sort()
    print(json.dumps({
        "records": args.records,
        "queries": args.queries,
        "p50_ms": statistics.median(latencies),
        "p95_ms": latencies[int(len(latencies) * 0.95) - 1],
        "p99_ms": latencies[int(len(latencies) * 0.99) - 1],
        "max_ms": max(latencies),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
