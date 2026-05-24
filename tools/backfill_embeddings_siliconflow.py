#!/usr/bin/env python3
"""一次性 embedding 回填：对 memories + conversation_logs 生成 SiliconFlow Qwen3 embedding"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import requests

PROVIDER = "siliconflow"
MODEL = os.getenv("MEMORYX_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunks(items, size: int):
    for i in range(0, len(items), size):
        yield items[i: i + size]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS memory_embeddings (
        id TEXT PRIMARY KEY,
        memory_id TEXT,
        source_table TEXT NOT NULL DEFAULT 'memories',
        source_id TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        dimensions INTEGER NOT NULL,
        vector_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_table, source_id, provider, model)
    );
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_memory_embeddings_source
    ON memory_embeddings(source_table, source_id, provider, model);
    """)
    conn.commit()


def fetch_rows(conn: sqlite3.Connection, include_conversations: bool) -> list[dict]:
    rows: list[dict] = []

    # memories（仅 active）
    for r in conn.execute("""
        SELECT id AS source_id, id AS memory_id, content
        FROM memories
        WHERE (active_state = 1 OR active_state = 'active')
          AND content IS NOT NULL
          AND trim(content) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM memory_embeddings e
            WHERE e.source_table = 'memories'
              AND e.source_id = memories.id
              AND e.provider = ?
              AND e.model = ?
          )
        ORDER BY created_at ASC;
    """, (PROVIDER, MODEL)):
        rows.append({
            "source_table": "memories",
            "source_id": r[0],
            "memory_id": r[1],
            "content": r[2],
        })

    if include_conversations:
        for r in conn.execute("""
            SELECT log_id AS source_id, content
            FROM conversation_logs
            WHERE content IS NOT NULL
              AND trim(content) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM memory_embeddings e
                WHERE e.source_table = 'conversation_logs'
                  AND e.source_id = conversation_logs.log_id
                  AND e.provider = ?
                  AND e.model = ?
              )
            ORDER BY created_at ASC;
        """, (PROVIDER, MODEL)):
            rows.append({
                "source_table": "conversation_logs",
                "source_id": r[0],
                "memory_id": None,
                "content": r[1],
            })

    return rows


def embed_batch(texts: list[str]) -> list[list[float]]:
    api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("MEMORYX_EMBEDDING_API_KEY")
    if not api_key:
        raise RuntimeError("SILICONFLOW_API_KEY 未设置")

    url = "https://api.siliconflow.cn/v1/embeddings"
    payload = {"model": MODEL, "input": texts}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(5):
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code in {429, 500, 502, 503, 504}:
            time.sleep(min(30, 2 ** attempt))
            continue
        r.raise_for_status()
        data = r.json()
        return [item["embedding"] for item in data["data"]]

    r.raise_for_status()
    raise RuntimeError("不可达")


def insert_vector(conn: sqlite3.Connection, row: dict, vector: list[float]) -> None:
    if not any(abs(x) > 1e-12 for x in vector):
        raise ValueError(f"全零向量: {row['source_table']}:{row['source_id']}")

    emb_id = sha256(f"{row['source_table']}:{row['source_id']}:{PROVIDER}:{MODEL}")
    conn.execute("""
        INSERT OR REPLACE INTO memory_embeddings(
            id, memory_id, source_table, source_id, content_hash,
            provider, model, dimensions, vector_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
    """, (
        emb_id,
        row["memory_id"],
        row["source_table"],
        row["source_id"],
        sha256(row["content"]),
        PROVIDER,
        MODEL,
        len(vector),
        json.dumps(vector, separators=(",", ":")),
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="MemoryX embedding backfill")
    parser.add_argument("--db", default=os.getenv("MEMORYX_DB_PATH", "data/memoryx.db"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--include-conversations", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB 不存在: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    ensure_schema(conn)

    rows = fetch_rows(conn, include_conversations=args.include_conversations)
    print(f"待处理: {len(rows)} 条  db={db_path}  model={MODEL}")

    if args.dry_run:
        print("--- Dry-run 预览（前 5 条）---")
        for row in rows[:5]:
            content_preview = row["content"][:80].replace("\n", " ")
            print(f"  [{row['source_table']}] {row['source_id']}: {content_preview}")
        conn.close()
        return

    done = 0
    for batch in chunks(rows, args.batch_size):
        texts = [r["content"] for r in batch]
        vectors = embed_batch(texts)
        if len(vectors) != len(batch):
            raise RuntimeError(f"向量数量不匹配: {len(vectors)} != {len(batch)}")

        with conn:
            for row, vector in zip(batch, vectors):
                try:
                    insert_vector(conn, row, vector)
                    done += 1
                except ValueError as e:
                    print(f"  跳过 {row['source_table']}:{row['source_id']}: {e}")

        print(f"  进度: {done}/{len(rows)}")

    # 汇总
    summary = conn.execute("""
        SELECT provider, model, COUNT(*) AS n, MIN(dimensions), MAX(dimensions)
        FROM memory_embeddings
        GROUP BY provider, model;
    """).fetchall()
    print(f"\n✅ 完成! 共 {done} 条")
    for r in summary:
        print(f"   provider={r[0]} model={r[1]}  count={r[2]}  dim=[{r[3]}-{r[4]}]")

    conn.close()


if __name__ == "__main__":
    main()
