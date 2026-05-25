#!/usr/bin/env python3
"""Generate scale dataset for MemoryX P9 benchmarks."""
from __future__ import annotations

import argparse, asyncio, json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOPICS = ["api","deployment","debugging","testing","database","security","performance","devops"]
TYPES = ["FACT","OBSERVATION","PREFERENCE","PROJECT","OPINION"]
SESSIONS = [f"s_{i:04d}" for i in range(200)]
ENTITIES = ["python","postgres","docker","kubernetes","redis","nginx","react","fastapi","sqlite","lancedb"]


async def generate(db_path: Path, *, memories: int = 1000, lessons: int = 100, entities: int = 100, batch_size: int = 500) -> dict:
    from memoryx.storage import MemoryRepository, MemoryRecord

    repo = MemoryRepository(db_path)
    await repo.open()
    stats = {"memories": 0, "lessons": 0, "entities": 0}

    print(f"Generating {memories} memories...")
    for start in range(0, memories, batch_size):
        chunk = min(batch_size, memories - start)
        try:
            async with repo.db.transaction() as conn:
                for j in range(chunk):
                    i = start + j
                    conn.execute(
                        "INSERT OR IGNORE INTO memories(id,memory_type,content,session_id,importance_score,confidence_score,metadata_json,active_state,checksum,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                        (f"pm-{i:06d}", random.choice(TYPES), f"Memory about {random.choice(TOPICS)}: {i}",
                         random.choice(SESSIONS) if random.random() < 0.7 else None,
                         round(random.uniform(0.1, 1.0), 2), round(random.uniform(0.3, 1.0), 2),
                         json.dumps({"entities": random.sample(ENTITIES, k=min(3, len(ENTITIES)))}),
                         "active", f"chk_pm{i}"),
                    )
            stats["memories"] += chunk
        except Exception as e:
            print(f"  batch err: {e}")
        if stats["memories"] % 2000 == 0:
            print(f"  {stats['memories']}/{memories}")

    print(f"Generating {lessons} lessons...")
    for i in range(lessons):
        try:
            await repo.db.execute(
                "INSERT OR IGNORE INTO lesson_memories(id,memory_id,lesson_text,policy_type,severity,trigger_patterns_json,evidence_count,confidence_score,active_state,metadata_json) VALUES (?,?,?,?,?,?,?,?,'active','{}')",
                (f"pl-{i:06d}", f"pm-{i:06d}", f"Lesson: check {random.choice(TOPICS)} before deploy",
                 random.choice(["warn","avoid"]), round(random.uniform(0.3,1.0),2),
                 json.dumps([random.choice(TOPICS)]), random.randint(1,5), round(random.uniform(0.5,1.0),2)),
            )
            stats["lessons"] += 1
        except Exception:
            pass

    print(f"Generating {entities} entities...")
    for i in range(entities):
        try:
            await repo.db.execute(
                "INSERT OR IGNORE INTO entities(id,name,entity_type,active_state,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,datetime('now'),'{}')",
                (f"pe-{i:06d}", f"{random.choice(ENTITIES)}_{i%50}", random.choice(["technology","project","tool"]), "active", f"chk_pe{i}"),
            )
            stats["entities"] += 1
        except Exception:
            pass

    await repo.close()
    print(f"Done: {stats}")
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("./data/p9_scale.db"))
    p.add_argument("--memories", type=int, default=1000)
    p.add_argument("--lessons", type=int, default=100)
    p.add_argument("--entities", type=int, default=100)
    p.add_argument("--batch", type=int, default=500)
    args = p.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()
    asyncio.run(generate(args.db, memories=args.memories, lessons=args.lessons, entities=args.entities, batch_size=args.batch))


if __name__ == "__main__":
    main()
