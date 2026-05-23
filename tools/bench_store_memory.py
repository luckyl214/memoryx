#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from uuid import uuid4

from memoryx.storage import MemoryRecord, MemoryRepository


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/bench_store.sqlite3"))
    parser.add_argument("--records", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    repo = MemoryRepository(args.db)
    await repo.open()
    sem = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []

    async def one(i: int) -> None:
        async with sem:
            start = time.perf_counter()
            await repo.store_memory(
                MemoryRecord(
                    id=f"bench-{uuid4().hex}",
                    memory_type="FACT",
                    content=f"benchmark memory {i}",
                    importance_score=0.5,
                    confidence_score=0.8,
                )
            )
            latencies.append((time.perf_counter() - start) * 1000)

    await asyncio.gather(*(one(i) for i in range(args.records)))
    await repo.close()
    latencies.sort()
    print(json.dumps({
        "records": args.records,
        "concurrency": args.concurrency,
        "p50_ms": statistics.median(latencies),
        "p95_ms": latencies[int(len(latencies) * 0.95) - 1],
        "p99_ms": latencies[int(len(latencies) * 0.99) - 1],
        "max_ms": max(latencies),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
