#!/usr/bin/env python3
"""MemoryX embedding 健康检查"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.getenv("MEMORYX_DB_PATH", "data/memoryx.db"))
    parser.add_argument("--min-coverage", type=float, default=0.95)
    parser.add_argument("--include-conversations", action="store_true")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found: {db}")
        return 2

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    # memories（兼容 active_state 为 INTEGER 或 TEXT）
    memories = conn.execute("""
        SELECT COUNT(*) AS n
        FROM memories
        WHERE (active_state = 1 OR active_state = 'active')
          AND content IS NOT NULL
          AND trim(content) <> '';
    """).fetchone()["n"]

    embedded_memories = conn.execute("""
        SELECT COUNT(DISTINCT source_id) AS n
        FROM memory_embeddings
        WHERE source_table='memories';
    """).fetchone()["n"]

    total = memories
    embedded = embedded_memories

    if args.include_conversations:
        conv = conn.execute("""
            SELECT COUNT(*) AS n
            FROM conversation_logs
            WHERE content IS NOT NULL
              AND trim(content) <> '';
        """).fetchone()["n"]
        emb_conv = conn.execute("""
            SELECT COUNT(DISTINCT source_id) AS n
            FROM memory_embeddings
            WHERE source_table='conversation_logs';
        """).fetchone()["n"]
        total += conv
        embedded += emb_conv

    coverage = embedded / total if total else 1.0

    bad_vectors = 0
    for r in conn.execute("SELECT id, vector_json FROM memory_embeddings;"):
        try:
            v = json.loads(r["vector_json"])
            if not v or not any(abs(float(x)) > 1e-12 for x in v):
                bad_vectors += 1
        except Exception:
            bad_vectors += 1

    result = {
        "db": str(db),
        "total_embed_sources": total,
        "embedded": embedded,
        "coverage": round(coverage, 4),
        "bad_vectors": bad_vectors,
        "status": "OK" if (coverage >= args.min_coverage and bad_vectors == 0) else "ERROR"
    }
    print(json.dumps(result, indent=2))

    if coverage < args.min_coverage:
        print(f"ERROR: embedding coverage {coverage:.2%} < {args.min_coverage:.2%}")
        return 1

    if bad_vectors:
        print(f"ERROR: bad/all-zero vectors found: {bad_vectors}")
        return 1

    print("OK: embedding health good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
