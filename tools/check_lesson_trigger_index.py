#!/usr/bin/env python3
"""Check lesson_triggers index consistency and optionally repair."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


async def check(db_path: Path, repair: bool = False) -> dict:
    from memoryx.storage import MemoryRepository

    repo = MemoryRepository(db_path)
    await repo.open()

    # Check if lesson_triggers table exists
    tables = await repo.db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='lesson_triggers';")
    has_triggers = len(tables) > 0

    if not has_triggers:
        print("lesson_triggers table does not exist — run migration 011 first")
        await repo.close()
        return {"has_table": False, "missing": 0, "repaired": 0, "total_lessons": 0}

    # Count lessons without trigger entries
    rows = await repo.db.fetchall("""
        SELECT lm.id, lm.trigger_patterns_json, lm.trigger_intents_json, lm.prohibited_patterns_json
        FROM lesson_memories lm
        WHERE lm.active_state = 'active'
          AND lm.id NOT IN (SELECT DISTINCT lesson_id FROM lesson_triggers WHERE active_state = 'active')
    """)

    missing = [dict(r) for r in rows]
    repaired_count = 0

    if missing:
        print(f"Found {len(missing)} lessons missing trigger index entries")
        if repair:
            for lesson in missing:
                try:
                    patterns = json.loads(lesson.get("trigger_patterns_json", "[]") or "[]")
                    intents = json.loads(lesson.get("trigger_intents_json", "[]") or "[]")
                    prohibited = json.loads(lesson.get("prohibited_patterns_json", "[]") or "[]")

                    for p in patterns:
                        await repo.db.execute(
                            "INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type, active_state) VALUES (?,?,?,?)",
                            (lesson["id"], str(p), "pattern", "active"),
                        )
                    for intent in intents:
                        await repo.db.execute(
                            "INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type, active_state) VALUES (?,?,?,?)",
                            (lesson["id"], str(intent), "intent", "active"),
                        )
                    for p in prohibited:
                        await repo.db.execute(
                            "INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type, active_state) VALUES (?,?,?,?)",
                            (lesson["id"], str(p), "prohibited", "active"),
                        )
                    repaired_count += 1
                except Exception as e:
                    print(f"  repair err for {lesson['id']}: {e}")
            print(f"Repaired {repaired_count} lessons")

    total = await repo.db.fetchone("SELECT COUNT(*) as cnt FROM lesson_memories WHERE active_state='active'")
    await repo.close()

    return {
        "has_table": True,
        "total_lessons": int(total["cnt"]) if total else 0,
        "missing_count": len(missing),
        "repaired_count": repaired_count,
    }


def main():
    p = argparse.ArgumentParser(description="Check/repair lesson_triggers index consistency")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--repair", action="store_true")
    args = p.parse_args()

    result = asyncio.run(check(args.db, repair=args.repair))
    print(f"\nResult: {json.dumps(result, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
