from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.bank import MemoryBank
from memoryx.storage import MemoryRecord, MemoryRepository


@pytest.mark.asyncio
async def test_memory_bank_stores_and_counts_by_bank(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "bank-count.db")
    await repo.open()

    bank_a = MemoryBank(bank_id="project-alpha", repository=repo)
    bank_b = MemoryBank(bank_id="project-beta", repository=repo)

    await bank_a.store("FACT", "alpha config", importance_score=0.9)
    await bank_a.store("PREFERENCE", "alpha likes async", importance_score=0.8)
    await bank_b.store("FACT", "beta config", importance_score=0.7)

    assert await bank_a.count() == 2
    assert await bank_b.count() == 1
    await repo.close()


@pytest.mark.asyncio
async def test_memory_bank_search_isolates_banks(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "bank-search.db")
    await repo.open()

    bank_a = MemoryBank(bank_id="alpha", repository=repo)
    bank_b = MemoryBank(bank_id="beta", repository=repo)

    await bank_a.store("PROJECT", "alpha project memory", importance_score=0.95)
    await bank_b.store("PROJECT", "beta project memory", importance_score=0.95)

    class DummyVS:
        async def search(self, *args, **kwargs):
            return []

    results_a = await bank_a.search("project", [1.0, 0.0], vector_store=DummyVS())
    results_b = await bank_b.search("project", [1.0, 0.0], vector_store=DummyVS())

    bank_ids_a = {r["memory_id"] for r in results_a}
    bank_ids_b = {r["memory_id"] for r in results_b}
    assert bank_ids_a.isdisjoint(bank_ids_b)
    await repo.close()


def test_memory_bank_template_resolution() -> None:
    resolved = MemoryBank.resolve_template("memory-{user}-{session}", user="example_user", session="s123")
    assert resolved == "memory-example_user-s123"

    # unknown placeholder stays as-is
    resolved = MemoryBank.resolve_template("bank-{unknown}", user="x")
    assert "{unknown}" in resolved


@pytest.mark.asyncio
async def test_memory_bank_clear_soft_deletes(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path / "bank-clear.db")
    await repo.open()

    bank = MemoryBank(bank_id="temp", repository=repo)
    await bank.store("FACT", "temporary", importance_score=0.5)

    assert await bank.count() >= 1
    cleared = await bank.clear()
    assert cleared >= 1
    assert await bank.count() == 0
    await repo.close()
