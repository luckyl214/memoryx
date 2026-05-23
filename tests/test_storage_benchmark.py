from __future__ import annotations

import time
from pathlib import Path

import pytest

from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_storage_benchmark_smoke(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "bench.db")
    await repo.open()

    started = time.perf_counter()
    for i in range(100):
        await repo.store_memory(MemoryRecord(memory_id=f"b{i}", memory_type="TASK", content=f"task {i}"))
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert len(await repo.search_full_text("task")) >= 1
    await repo.close()
