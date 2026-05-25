#!/usr/bin/env python3
"""P14.4.3 Feishu Card Ownership Gate — 连接真实 DB 验证。

检查项（硬性）：
1. 最新 job：state=done, visible_state=done, phase=done
2. card_message_id 非空（有初始卡片 message_id）
3. revision >= 4（至少 received + thinking + writing + done）
4. DLQ = 0
5. trace 包含 card_initial_sent 和多次 card_patch_done
6. card_patch_done 至少 3 次（thinking + writing + done 各一次）
"""
from __future__ import annotations

import os
import sqlite3
import sys


QUEUE_DB = os.getenv("QUEUE_DB", "/home/lucky/memoryx/data/feishu_queue.db")
MEMORYX_DB = os.getenv("MEMORYX_DB", "/home/lucky/memoryx/data/memoryx.db")

pass_count = 0
fail_count = 0


def ok(msg: str) -> None:
    global pass_count
    pass_count += 1
    print(f"  ✅ {msg}")


def fail(msg: str, fatal: bool = True) -> None:
    global fail_count
    fail_count += 1
    print(f"  ❌ {msg}")
    if fatal:
        sys.exit(1)


def main() -> int:
    global pass_count, fail_count

    print("=" * 60)
    print("P14.4.3 Feishu Card Ownership Gate")
    print("(connects to real feishu_queue.db)")
    print("=" * 60)
    print()

    # ── 1. 连接 DB ──
    if not os.path.exists(QUEUE_DB):
        fail(f"QUEUE_DB not found: {QUEUE_DB}")
        return 1
    ok(f"QUEUE_DB exists: {QUEUE_DB}")

    conn = sqlite3.connect(QUEUE_DB)
    conn.row_factory = sqlite3.Row

    # ── 2. 最新 job ──
    rows = conn.execute(
        """
        SELECT job_id, state, visible_state, phase, revision, card_message_id, attempts
        FROM feishu_jobs
        ORDER BY created_at DESC
        LIMIT 10;
        """
    ).fetchall()

    if not rows:
        fail("no feishu_jobs found")
        return 1
    ok(f"feishu_jobs count: {len(rows)}")

    latest = rows[0]
    jid = latest["job_id"]
    print(f"\nLatest job: {jid}")
    print(f"  state={latest['state']} visible_state={latest['visible_state']}")
    print(f"  phase={latest['phase']} revision={latest['revision']}")
    print(f"  card_message_id={latest['card_message_id']}")
    print(f"  attempts={latest['attempts']}")
    print()

    # ── 3. 硬检查 ──
    if latest["state"] != "done":
        fail("state != done")
    else:
        ok("state = done")

    if latest["visible_state"] != "done":
        fail("visible_state != done")
    else:
        ok("visible_state = done")

    if latest["phase"] != "done":
        fail(f"phase != done (got '{latest['phase']}')")
    else:
        ok("phase = done")

    cmid = latest["card_message_id"]
    if not cmid:
        fail("card_message_id is EMPTY — no initial card was saved")
    else:
        ok(f"card_message_id = {cmid[:30]}...")

    rev = int(latest["revision"] or 0)
    if rev < 4:
        fail(f"revision too low: {rev} (expected >= 4 for multi-phase patching)")
    else:
        ok(f"revision = {rev} (>= 4)")

    att = int(latest["attempts"] or 0)
    if att > 2:
        fail(f"attempts > 2: {att} (may indicate re-claim issues)")
    else:
        ok(f"attempts = {att} (<= 2)")

    # ── 4. DLQ ──
    dlq_row = conn.execute("SELECT COUNT(*) AS n FROM feishu_dead_letters").fetchone()
    dlq = int(dlq_row["n"] or 0)
    if dlq != 0:
        fail(f"DLQ not empty: {dlq}")
    else:
        ok("DLQ = 0")

    # ── 5. Trace 检查 ──
    if os.path.exists(MEMORYX_DB):
        trace_conn = sqlite3.connect(MEMORYX_DB)
        trace_conn.row_factory = sqlite3.Row
        traces = trace_conn.execute(
            """
            SELECT event_type, phase, payload_json
            FROM feishu_trace_events
            WHERE job_id=?
            ORDER BY id ASC;
            """,
            (jid,),
        ).fetchall()

        events = [r["event_type"] for r in traces]

        if not events:
            fail(f"no trace events for job {jid}")
        else:
            ok(f"trace events: {len(events)}")

        # 必须包含这些事件
        required = [
            "event_accepted",
            "card_initial_sent",
            "state_transition",
            "card_patch_done",
            "job_done",
        ]
        missing = [e for e in required if e not in events]
        if missing:
            fail(f"missing trace events: {missing}")
        else:
            ok("trace contains all required events")

        # card_patch_done 至少 3 次
        patch_count = events.count("card_patch_done")
        if patch_count < 3:
            fail(f"card_patch_done only {patch_count} times (expected >= 3)")
        else:
            ok(f"card_patch_done = {patch_count} times (>= 3)")

        # 检查 card_initial_sent 的 payload 中有 card_message_id
        for r in traces:
            if r["event_type"] == "card_initial_sent":
                import json
                try:
                    payload = json.loads(r["payload_json"])
                    if payload.get("card_message_id"):
                        ok("card_initial_sent includes card_message_id in payload")
                    else:
                        fail("card_initial_sent missing card_message_id in payload")
                except json.JSONDecodeError:
                    fail("card_initial_sent payload is not valid JSON")
                break
        else:
            fail("card_initial_sent trace event not found")

        # 检查 final card_patch_done 带有 final_view=true
        for r in reversed(traces):
            if r["event_type"] == "card_patch_done":
                import json
                try:
                    payload = json.loads(r["payload_json"])
                    if payload.get("final_view"):
                        ok("final card_patch_done includes final_view=true")
                        break
                    else:
                        fail("final card_patch_done missing final_view=true")
                        break
                except json.JSONDecodeError:
                    continue

        trace_conn.close()
    else:
        fail(f"MEMORYX_DB not found: {MEMORYX_DB}")

    # ── 6. 所有 job 的 card_message_id 非空 ──
    empty_id = conn.execute(
        "SELECT COUNT(*) AS n FROM feishu_jobs WHERE card_message_id IS NULL OR card_message_id = ''"
    ).fetchone()["n"]
    if empty_id > 0:
        fail(f"{empty_id} job(s) have empty card_message_id", fatal=False)
    else:
        ok("all jobs have card_message_id")

    conn.close()

    # ── 总结 ──
    print()
    print(f"PASS: {pass_count}  FAIL: {fail_count}")
    print("=" * 60)

    if fail_count > 0:
        print(f"P14.4.3 FEISHU CARD OWNERSHIP GATE: FAIL ({fail_count} failures)")
        return 1
    else:
        print("P14.4.3 FEISHU CARD OWNERSHIP GATE: PASS ✅")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())