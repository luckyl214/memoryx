"""P0-F: EmbeddingCache LRU tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryx.embeddings.cache_layer import EmbeddingCache


@pytest.mark.asyncio
async def test_cache_get_set_basic(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.json")
    vec = [0.1, 0.2, 0.3]
    await cache.set("key1", vec)
    result = await cache.get("key1")
    assert result == vec


@pytest.mark.asyncio
async def test_cache_get_missing(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.json")
    assert await cache.get("nonexistent") is None


@pytest.mark.asyncio
async def test_cache_lru_eviction(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.json", max_entries=3, persist_every=100)
    for i in range(5):
        await cache.set(f"key{i}", [float(i)])

    # Oldest keys (key0, key1) should be evicted
    assert await cache.get("key0") is None
    assert await cache.get("key1") is None
    assert await cache.get("key4") == [4.0]


@pytest.mark.asyncio
async def test_cache_get_promotes_lru(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.json", max_entries=2, persist_every=100)
    await cache.set("a", [1.0])
    await cache.set("b", [2.0])
    # Access "a" → promotes to most-recent
    await cache.get("a")
    # Insert "c" → evicts "b" (now least-recent)
    await cache.set("c", [3.0])
    assert await cache.get("a") == [1.0]
    assert await cache.get("b") is None
    assert await cache.get("c") == [3.0]


@pytest.mark.asyncio
async def test_cache_persist_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "cache_persist.json"
    cache1 = EmbeddingCache(path, persist_every=1)
    await cache1.set("x", [7.0, 8.0])
    await cache1.set("y", [9.0, 10.0])
    await cache1.flush()  # force write

    # Reload from disk
    cache2 = EmbeddingCache(path)
    assert await cache2.get("x") == [7.0, 8.0]
    assert await cache2.get("y") == [9.0, 10.0]


@pytest.mark.asyncio
async def test_cache_atomic_write_no_corruption(tmp_path: Path) -> None:
    """P0-F: tmp file + os.replace should prevent partial writes."""
    path = tmp_path / "cache_atomic.json"
    cache = EmbeddingCache(path, persist_every=1)
    await cache.set("safe", [42.0])
    await cache.flush()

    # File exists and is valid JSON
    assert path.exists()
    import json
    data = json.loads(path.read_text())
    assert "safe" in data
    assert data["safe"] == [42.0]
