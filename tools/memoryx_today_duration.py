#!/usr/bin/env python3
"""MemoryX Today Duration — show today's learning time by entity.

Usage:
    python tools/memoryx_today_duration.py
    python tools/memoryx_today_duration.py --entity xhs-learning
    python tools/memoryx_today_duration.py --entity xhs
    python tools/memoryx_today_duration.py --days 7
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path


def _fmt(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show learning duration from MemoryX")
    parser.add_argument("--db", default="/home/lucky/memoryx/data/memoryx.db",
                        help="MemoryX database path")
    parser.add_argument("--entity", default="",
                        help="Filter by entity (LIKE match, e.g. 'xhs' or 'xhs-learning')")
    parser.add_argument("--days", type=int, default=1,
                        help="Number of days to look back (default: 1 = today)")
    parser.add_argument("--detail", action="store_true",
                        help="Show individual task breakdown")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"  Database not found: {db}")
        return 1

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    since = (date.today() - timedelta(days=args.days - 1)).isoformat()

    where_clause = "date(start_time) >= ?"
    params = [since]
    if args.entity:
        where_clause += " AND entity_id LIKE ?"
        params.append(f"{args.entity}%")

    # Summary by entity
    rows = conn.execute(
        f"""
        SELECT entity_id,
               COALESCE(json_extract(metadata_json, '$.task_type'), 'unknown') AS task_type,
               SUM(duration_seconds) AS total_seconds,
               COUNT(*) AS n
        FROM task_durations
        WHERE {where_clause}
        GROUP BY entity_id, task_type
        ORDER BY entity_id, total_seconds DESC;
        """,
        params,
    ).fetchall()

    total_all = sum(int(r["total_seconds"] or 0) for r in rows)

    if not rows:
        entity_tag = f" for '{args.entity}'" if args.entity else ""
        print(f"  No completed tasks{entity_tag} since {since}")
        return 0

    print(f"  Period: {since} → today ({args.days}d)")
    if args.entity:
        print(f"  Entity filter: '{args.entity}'\n")
    print(f"  Total: {_fmt(total_all)} ({total_all}s)")
    print()

    current_entity = None
    for r in rows:
        entity = r["entity_id"]
        sec = int(r["total_seconds"] or 0)
        n = r["n"]
        if entity != current_entity:
            print(f"  [{entity}]")
            current_entity = entity
        print(f"    {r['task_type']}: {_fmt(sec)} ({n} tasks)")

    # Detail mode: individual task list
    if args.detail and rows:
        print()
        print("  ── Individual tasks ──")
        detail_rows = conn.execute(
            f"""
            SELECT task_id, session_id, entity_id,
                   COALESCE(json_extract(metadata_json, '$.task_type'), 'unknown') AS task_type,
                   COALESCE(json_extract(metadata_json, '$.title'), '') AS title,
                   duration_seconds, start_time,
                   json_extract(metadata_json, '$.summary') AS summary
            FROM task_durations
            WHERE {where_clause}
            UNION ALL
            SELECT task_id, session_id, entity_id, task_type, title,
                   duration_seconds, start_time,
                   json_extract(metadata_json, '$.summary') AS summary
            FROM tasks
            WHERE {where_clause} AND duration_seconds IS NOT NULL
            ORDER BY start_time DESC
            LIMIT 50;
            """,
            params * 2,
        ).fetchall()

        for dr in detail_rows:
            sec = dr["duration_seconds"]
            summary = dr["summary"] or ""
            print(
                f"    {dr['start_time'][:19]}  "
                f"{_fmt(int(sec)) if sec else '--'}  "
                f"{dr['entity_id']}/{dr['task_type']}: "
                f"{dr['title']}"
            )
            if summary:
                print(f"      → {summary[:120]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())