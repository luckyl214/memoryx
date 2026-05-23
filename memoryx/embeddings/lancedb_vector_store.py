"""P1: LanceDB 向量存储 — 替换 JSON VectorStore。

兼容旧 API：open / upsert / search / delete。
新增：batch_upsert / migrate_json_vector_store / benchmark / ensure_index。
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa
from lancedb.table import Table


class LanceDBVectorStore:
    """LanceDB-backed vector store with auto-indexing and benchmark support."""

    def __init__(
        self,
        uri: Path | str,
        *,
        table_name: str = "vectors",
        auto_index_threshold: int = 1000,
    ) -> None:
        self.uri = str(uri)
        self.table_name = table_name
        self.auto_index_threshold = auto_index_threshold
        self._db: lancedb.DBConnection | None = None
        self._table: Table | None = None
        self._lock = asyncio.Lock()
        self._opened = False

    # ── Lifecycle ─────────────────────────────────────────────────

    async def open(self) -> None:
        if self._opened:
            return
        async with self._lock:
            if self._opened:
                return
            self._db = await asyncio.to_thread(lancedb.connect, self.uri)
            try:
                self._table = await asyncio.to_thread(
                    self._db.open_table, self.table_name
                )
            except Exception:
                # Table doesn't exist yet — will be created on first upsert
                self._table = None
            self._opened = True

    # ── Core API (compatible with VectorStore) ─────────────────────

    async def upsert(
        self,
        memory_id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.open()
        return await self.batch_upsert([(memory_id, vector, metadata or {})])

    async def batch_upsert(
        self,
        entries: list[tuple[str, list[float], dict[str, Any]]],
    ) -> None:
        """P1: batch upsert multiple vectors at once."""
        if not entries:
            return
        await self.open()
        records = [
            {
                "memory_id": mem_id,
                "vector": np.array(vec, dtype=np.float32),
                "dimension": len(vec),
                "metadata_json": json.dumps(meta or {}, ensure_ascii=False),
            }
            for mem_id, vec, meta in entries
        ]
        async with self._lock:
            if self._table is None:
                # Create table schema first (no data)
                schema = pa.schema(
                    [
                        pa.field("memory_id", pa.string()),
                        pa.field("vector", pa.list_(pa.float32(), list_size=len(records[0]["vector"]))),
                        pa.field("dimension", pa.int32()),
                        pa.field("metadata_json", pa.string()),
                    ]
                )
                try:
                    self._table = await asyncio.to_thread(
                        self._db.create_table,
                        self.table_name,
                        schema=schema,
                    )
                except Exception:
                    # Table may already exist, try opening
                    self._table = await asyncio.to_thread(
                        self._db.open_table, self.table_name
                    )
            tbl = self._table
            data = pa.Table.from_pylist(records, schema=tbl.schema)
            await asyncio.to_thread(tbl.add, data, mode="append")
            await self._maybe_index(table=tbl)

    async def search(
        self, query_vector: list[float], limit: int = 10
    ) -> list[dict[str, Any]]:
        await self.open()
        if self._table is None:
            return []
        vec = np.array(query_vector, dtype=np.float32)
        tbl = self._table
        try:
            qb = await asyncio.to_thread(tbl.search, vec)
            qb = await asyncio.to_thread(qb.limit, limit)
            results = await asyncio.to_thread(qb.to_list)
        except Exception:
            # Fall back to brute-force if indexed search fails
            all_rows = await asyncio.to_thread(tbl.to_arrow)
            pylist = all_rows.to_pylist()
            results = self._brute_force(vec, pylist, limit)
        return [
            {
                "memory_id": row.get("memory_id", ""),
                "score": float(row.get("_distance", 0.0)),
            }
            for row in results
        ]

    async def delete(self, memory_id: str) -> None:
        await self.open()
        async with self._lock:
            if self._table is None:
                return
            try:
                await asyncio.to_thread(
                    self._table.delete,
                    f"memory_id = '{memory_id}'",
                )
            except Exception:
                pass

    # ── Index management ──────────────────────────────────────────

    async def ensure_index(self) -> None:
        """Force index creation regardless of threshold."""
        await self.open()
        async with self._lock:
            if self._table is None:
                return
            await self._do_index(self._table)

    async def _maybe_index(self, *, table: Table) -> None:
        """Auto-create IVF_PQ index when count >= auto_index_threshold."""
        count = await asyncio.to_thread(table.count_rows)
        if count >= self.auto_index_threshold:
            await self._do_index(table)

    async def _do_index(self, table: Table) -> None:
        try:
            await asyncio.to_thread(
                table.create_index,
                metric="cosine",
                num_partitions=max(8, int(table.count_rows() / 2000)),
            )
        except Exception:
            pass

    # ── Migration ─────────────────────────────────────────────────

    async def migrate_json_vector_store(self, json_path: Path) -> int:
        """P1: Migrate from old JSON VectorStore to LanceDB."""
        if not json_path.exists():
            return 0
        data = json.loads(json_path.read_text(encoding="utf-8"))
        entries = [
            (mem_id, [float(v) for v in item["vector"]], item.get("metadata", {}))
            for mem_id, item in data.items()
        ]
        await self.batch_upsert(entries)
        return len(entries)

    # ── Benchmark ─────────────────────────────────────────────────

    async def benchmark(self) -> dict:
        """P1: Return benchmark stats for the current table."""
        await self.open()
        if self._table is None:
            return {"count": 0, "indexed": False}
        count = await asyncio.to_thread(self._table.count_rows)
        return {
            "count": count,
            "uri": self.uri,
            "table_name": self.table_name,
        }

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _brute_force(
        query: np.ndarray, rows: list[dict], limit: int
    ) -> list[dict]:
        scored = []
        for row in rows:
            vec = np.array(row.get("vector", []), dtype=np.float32)
            if len(vec) == 0:
                continue
            dot = float(np.dot(query, vec))
            q_norm = float(np.linalg.norm(query))
            v_norm = float(np.linalg.norm(vec))
            if q_norm == 0.0 or v_norm == 0.0:
                score = 0.0
            else:
                score = dot / (q_norm * v_norm)
            scored.append({**row, "_distance": score})
        scored.sort(key=lambda x: x["_distance"], reverse=True)
        return scored[:limit]


# ── CLI entry point ───────────────────────────────────────────────

def _benchmark_cli():
    """P1 CLI: python -m memoryx.embeddings.lancedb_vector_store benchmark ..."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["benchmark", "migrate"])
    parser.add_argument("--lancedb", default="data/lancedb_bench")
    parser.add_argument("--dimension", type=int, default=768)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--queries", type=int, default=300)
    parser.add_argument("--json-source", default="data/vectors.json")
    args = parser.parse_args()

    async def _run():
        store = LanceDBVectorStore(args.lancedb)

        if args.command == "benchmark":
            print(f"Inserting {args.count} vectors (dim={args.dimension})...")
            t0 = time.perf_counter()
            batch = []
            for i in range(args.count):
                vec = np.random.randn(args.dimension).astype(np.float32).tolist()
                batch.append((f"id-{i}", vec, {}))
                if len(batch) >= 1000:
                    await store.batch_upsert(batch)
                    batch = []
            if batch:
                await store.batch_upsert(batch)
            insert_time = time.perf_counter() - t0
            print(f"Insert: {insert_time:.2f}s ({args.count / insert_time:.0f} vectors/s)")

            await store.ensure_index()

            # Query benchmark
            print(f"Running {args.queries} queries (top 10)...")
            query_times: list[float] = []
            for _ in range(args.queries):
                q = np.random.randn(args.dimension).astype(np.float32).tolist()
                t0 = time.perf_counter()
                await store.search(q, limit=10)
                query_times.append(time.perf_counter() - t0)

            query_times.sort()
            p50 = query_times[len(query_times) // 2] * 1000
            p95 = query_times[int(len(query_times) * 0.95)] * 1000
            print(f"Top10 p50: {p50:.1f}ms  p95: {p95:.1f}ms")
            if p50 < 30 and p95 < 80:
                print("✅ PASS: Within targets (p50 < 30ms, p95 < 80ms)")
            else:
                print("⚠️  Above target thresholds")

        elif args.command == "migrate":
            count = await store.migrate_json_vector_store(Path(args.json_source))
            print(f"Migrated {count} vectors from {args.json_source}")

    asyncio.run(_run())


if __name__ == "__main__":
    _benchmark_cli()
