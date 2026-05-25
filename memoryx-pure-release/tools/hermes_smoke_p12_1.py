#!/usr/bin/env python3
"""Hermes P12.1 smoke test — validates MemoryX returns to Hermes hooks directly."""
from __future__ import annotations

import asyncio
from pathlib import Path

from memoryx.hermes_bridge import HermesMemoryBridge
from memoryx.storage import MemoryRecord, MemoryRepository


async def main():
    db_path = Path("./data/hermes_smoke_p12_1.sqlite3")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    repo = MemoryRepository(db_path)
    await repo.open()

    # Seed high-risk lesson
    await repo.store_memory(MemoryRecord(
        id="smoke-lesson-memory", memory_type="LESSON",
        content="Never deploy production with --force without dry-run and confirmation.",
        importance_score=0.95, confidence_score=0.95,
    ))
    await repo.db.execute(
        """INSERT OR IGNORE INTO lesson_memories(
            id,memory_id,lesson_text,policy_type,severity,trigger_intents_json,
            trigger_patterns_json,prohibited_patterns_json,recommended_action,
            evidence_count,confidence_score,active_state
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("smoke-lesson","smoke-lesson-memory",
         "Never deploy --force without dry-run and confirmation.",
         "warn",0.95,'["deployment"]','["deploy","production","--force"]',
         '["--force"]',"require_dry_run_and_confirmation",3,0.95,"active"))
    try:
        await repo.db.execute(
            """INSERT OR IGNORE INTO lesson_triggers(lesson_id,trigger,trigger_type,active_state)
            VALUES ('smoke-lesson','deployment','intent','active'),
                   ('smoke-lesson','deploy','pattern','active'),
                   ('smoke-lesson','production','pattern','active'),
                   ('smoke-lesson','--force','prohibited','active')""")
    except Exception:
        pass

    bridge = HermesMemoryBridge(repository=repo, query_api=None)

    # 1. on_user_message
    r = await bridge.on_user_message(
        session_id="smoke-p12-1",
        content="我要部署到生产环境，可能需要 --force。")
    assert r is not None, "on_user_message returned None"
    assert "MemoryX Safety Contract" in r.context_block
    print("[OK] on_user_message → context_block")

    # 2. on_tool_call
    d = await bridge.on_tool_call(
        session_id="smoke-p12-1", tool_name="shell",
        args={"cmd": "deploy production --force"}, intent="deployment")
    assert d is not None
    assert d.requires_user
    assert d.decision in {"require_dry_run","require_confirmation","require_tool_verification","block"}
    assert d.guard_block
    print(f"[OK] on_tool_call → {d.decision}")

    # 3. on_assistant_response
    a = await bridge.on_assistant_response(
        session_id="smoke-p12-1",
        question="Can MemoryX guarantee unsupported facts?",
        content="MemoryX guarantees every unsupported external claim is true.")
    assert a is not None
    assert a.decision in {"allow","warn","block"}
    print(f"[OK] on_assistant_response → {a.decision}")

    # 4. on_session_end
    s = await bridge.on_session_end(session_id="smoke-p12-1")
    assert s is not None
    print("[OK] on_session_end → narrative reflection")

    await repo.close()
    print("\n✅ Hermes smoke PASS — all 4 links verified")


if __name__ == "__main__":
    asyncio.run(main())
