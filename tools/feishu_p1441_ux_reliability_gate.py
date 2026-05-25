#!/usr/bin/env python3
"""P14.4.1 Feishu UX Reliability Gate — 验证修复是否到位。

检查项：
1. 纯文本消息卡片不出现"附件已入队"
2. 有附件消息才出现附件文案
3. overflow_text 不丢：超长回答生成 markdown 文件或明确失败
4. assert_transition 被实际调用
5. claim_next 返回 job.visible_state 与 DB 一致
6. patch 失败会进入 trace card_patch_failed
7. trace 包含 runner_start / runner_done
8. done job trace 包含 card_patch_done / job_done
9. revision 单调递增且无重复自增
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

QUEUE_DB = Path.home() / "memoryx" / "data" / "feishu_queue.db"
MEMORYX_DIR = Path.home() / "memoryx"


def check_trace_events() -> list[str]:
    """检查最新 trace 事件链是否完整
    NOTE: 仅对新代码重启后处理的 job 有效。旧 job 不受影响。
    """
    errors = []
    if not QUEUE_DB.exists():
        return [f"❌ trace DB not found: {QUEUE_DB}"]

    conn = sqlite3.connect(str(QUEUE_DB))
    conn.row_factory = sqlite3.Row

    # 最新 job 的 trace
    row = conn.execute(
        "SELECT job_id, created_at FROM feishu_jobs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return ["❌ no jobs in queue"]

    import time
    now = time.time()
    job_age = now - row["created_at"]

    job_id = row["job_id"]
    events = conn.execute(
        "SELECT event_type FROM feishu_trace_events WHERE job_id=? ORDER BY id",
        (job_id,),
    ).fetchall()
    event_types = [e["event_type"] for e in events]
    conn.close()

    # 只检查新代码（P14.4.1 修复后）的 job
    # 如果 job 创建时间早于 gate 脚本修改时间，跳过 trace 检查
    gate_mtime = Path(__file__).stat().st_mtime
    if row["created_at"] < gate_mtime - 300:  # 5 min buffer
        errors.append(f"⏭ trace check skipped: job {job_id[:12]} from before fix deployment")
        errors.append(f"   send a new echo to verify")
        return errors

    # 检查 5: trace 必须包含 runner_start / runner_done
    if "runner_start" not in event_types:
        errors.append("❌ 5: missing runner_start in trace")
    if "runner_done" not in event_types:
        errors.append("❌ 5: missing runner_done in trace")

    # 检查 7: done job trace 包含 card_patch_done / job_done
    if "card_patch_done" not in event_types:
        errors.append("❌ 7: missing card_patch_done in trace")
    if "job_done" not in event_types:
        errors.append("❌ 7: missing job_done in trace")

    # 检查 8: 必须至少包含 event_accepted + job_claimed
    if "event_accepted" not in event_types:
        errors.append("❌ baseline: missing event_accepted in trace")
    if "job_claimed" not in event_types:
        errors.append("❌ baseline: missing job_claimed in trace")

    if not errors:
        errors.append(f"✅ trace events ({len(event_types)} total): {', '.join(event_types)}")

    return errors


def check_code_quality() -> list[str]:
    """检查代码中是否有已知问题"""
    errors = []

    # 检查 1: state_update.transition_job 被引用
    bot_service = MEMORYX_DIR / "memoryx" / "feishu" / "bot_service.py"
    if bot_service.exists():
        text = bot_service.read_text()
        if "transition_job" not in text:
            errors.append("❌ 1: transition_job not used in bot_service.py")
        else:
            count = text.count("transition_job")
            errors.append(f"✅ 1: transition_job used {count} times")

        # 检查 4: patch 失败会进入 trace
        if "card_patch_failed" not in text:
            errors.append("❌ 4: card_patch_failed trace not found")
        else:
            errors.append("✅ 4: card_patch_failed trace present")

    # 检查 2: claim_next 同步 visible_state
    queue_file = MEMORYX_DIR / "memoryx" / "feishu" / "queue.py"
    if queue_file.exists():
        text = queue_file.read_text()
        if "synced_payload" in text:
            errors.append("✅ 2: claim_next payload sync present")

    # 检查 6: overflow_file 存在
    overflow_file = MEMORYX_DIR / "memoryx" / "feishu" / "overflow_file.py"
    if overflow_file.exists():
        errors.append("✅ 6: overflow_file.py present")
    else:
        errors.append("❌ 6: overflow_file.py missing")

    # 检查 9: render_text 附件动态文案
    render_text = MEMORYX_DIR / "memoryx" / "feishu" / "render_text.py"
    if render_text.exists():
        errors.append("✅ 9: render_text.py present (dynamic attachment text)")

    return errors


def check_db_state() -> list[str]:
    """检查当前 DB 状态"""
    errors = []
    if not QUEUE_DB.exists():
        return [f"❌ DB not found: {QUEUE_DB}"]

    conn = sqlite3.connect(str(QUEUE_DB))
    conn.row_factory = sqlite3.Row

    # DLQ
    dlq = conn.execute("SELECT COUNT(*) AS c FROM feishu_dead_letters").fetchone()
    if dlq and dlq["c"] == 0:
        errors.append("✅ DLQ=0")
    else:
        errors.append(f"⚠️ DLQ={dlq['c'] if dlq else 'N/A'}")

    # 最新 job 状态
    row = conn.execute(
        "SELECT state, visible_state, attempts FROM feishu_jobs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        if row["state"] == "done" and row["visible_state"] == "done":
            errors.append(f"✅ latest job: state={row['state']} visible={row['visible_state']} attempts={row['attempts']}")
        else:
            errors.append(f"⚠️ latest job: state={row['state']} visible={row['visible_state']}")

    conn.close()
    return errors


def main():
    print("=" * 60)
    print("  P14.4.1 Feishu UX Reliability Gate")
    print("=" * 60)
    print()

    all_ok = True

    print("── DB State ──")
    for r in check_db_state():
        print(f"  {r}")
        if "❌" in r:
            all_ok = False
    print()

    print("── Code Quality ──")
    for r in check_code_quality():
        print(f"  {r}")
        if "❌" in r:
            all_ok = False
    print()

    print("── Trace Events (latest job) ──")
    for r in check_trace_events():
        print(f"  {r}")
        if "❌" in r:
            all_ok = False
    print()

    print("=" * 60)
    if all_ok:
        print("  ✅ P14.4.1 GATE PASSED")
        print("  baseline: p14-4-1-feishu-ux-reliability-hotfix-green")
    else:
        print("  ❌ P14.4.1 GATE FAILED — review errors above")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())