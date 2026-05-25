#!/usr/bin/env python3
"""飞书全链路追踪 CLI — 查任意 job 的完整处理链路。

用法：
    python tools/feishu_trace.py --job-id <job_id>
    python tools/feishu_trace.py --job-id <job_id> --json
    python tools/feishu_trace.py --db-path /path/to/trace.db --job-id <job_id>
    python tools/feishu_trace.py --recent  # 最近的 10 个 job
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 尝试从 memoryx.feishu 导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoryx.feishu import FeishuTraceStore


# ── 默认 trace DB 路径查找 ──
DEFAULT_DB_CANDIDATES = [
    Path.home() / ".hermes" / "feishu_trace.db",
    Path("/tmp/feishu_trace.db"),
    Path("feishu_trace.db"),
]


def find_trace_db() -> str | None:
    for p in DEFAULT_DB_CANDIDATES:
        if p.exists():
            return str(p)
    return None


# ── 阶段标记 ──
PHASE_ICONS = {
    "received": "📥",
    "prepare": "🔧",
    "context": "🧠",
    "generate": "🤖",
    "verify": "🛡️",
    "reflect": "📝",
    "error": "🔴",
    "done": "✅",
}

EVENT_ICONS = {
    "event_accepted": "📩",
    "job_claimed": "🔄",
    "attachment_downloaded": "📎",
    "attachment_unusable": "⚠️",
    "attachment_failed": "❌",
    "overflow": "📤",
    "job_failed": "💥",
    "job_done": "✅",
    "tool_start": "🔛",
    "tool_end": "✅",
    "guard_warn": "🟡",
    "guard_pass": "🟢",
}


def format_timeline(timeline: list[dict], verbose: bool = False) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append("  飞书全链路追踪时间线")
    lines.append("=" * 64)

    if not timeline:
        lines.append("  (无记录)")
        return "\n".join(lines)

    for entry in timeline:
        ts = entry.get("time", 0)
        # 格式化成 HH:MM:SS
        import datetime
        dt = datetime.datetime.fromtimestamp(ts)
        time_str = dt.strftime("%H:%M:%S.%f")[:12]

        phase = entry.get("phase", "")
        event = entry.get("event", "")
        payload = entry.get("payload", {})

        icon = EVENT_ICONS.get(event, PHASE_ICONS.get(phase, "•"))

        summary = payload.get("summary", "")
        error = payload.get("error", "")
        reason = payload.get("reason", "")
        name = payload.get("name", "")
        status = payload.get("status", "")

        line_parts = [f"  {icon} {time_str}"]
        line_parts.append(f"[{phase}]")
        line_parts.append(event)

        if summary:
            line_parts.append(f"· {summary}")
        if error and verbose:
            line_parts.append(f"\n    ⚠️ Error: {error[:200]}")
        if reason:
            line_parts.append(f"· {reason}")
        if name and status:
            line_parts.append(f"· {name} ({status})")

        lines.append(" ".join(line_parts))

    lines.append("=" * 64)
    return "\n".join(lines)


def format_summary(events: list[dict]) -> str:
    lines = []
    phases = set()
    total = len(events)
    errors = [e for e in events if e.get("event_type") == "job_failed"]
    warnings = [e for e in events if "guard_warn" in e.get("event_type", "")]
    attachments = [e for e in events if "attachment" in e.get("event_type", "")]

    for e in events:
        phases.add(e.get("phase", ""))

    lines.append(f"  总事件数: {total}")
    lines.append(f"  阶段: {', '.join(sorted(phases))}")
    if errors:
        lines.append(f"  ❌ 错误: {len(errors)}")
    if warnings:
        lines.append(f"  🟡 警告: {len(warnings)}")
    if attachments:
        ok = sum(1 for e in attachments if "downloaded" in e.get("event_type", ""))
        failed = sum(1 for e in attachments if "failed" in e.get("event_type", ""))
        lines.append(f"  📎 附件: {ok} OK, {failed} failed")

    return "\n".join(lines)


def cmd_trace(args: argparse.Namespace) -> int:
    db_path = args.db_path or find_trace_db()
    if not db_path:
        print("❌ 找不到 trace DB。用 --db-path 指定路径。")
        return 1

    try:
        store = FeishuTraceStore(db_path)
    except Exception as e:
        print(f"❌ 无法打开 trace DB: {e}")
        return 1

    job_id = args.job_id
    events = store.get_events(job_id)
    timeline = store.get_timeline(job_id)

    if args.json:
        print(json.dumps({
            "job_id": job_id,
            "events": events,
            "timeline": timeline,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"\n📋  Job: {job_id}")
    print(f"📁  DB:  {db_path}\n")

    if not events:
        print("  (无记录 — job 可能还未被处理或 trace_id 错误。)")
        return 0

    print(format_summary(events))
    print()
    print(format_timeline(timeline, verbose=args.verbose))

    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    db_path = args.db_path or find_trace_db()
    if not db_path:
        print("❌ 找不到 trace DB。用 --db-path 指定路径。")
        return 1

    try:
        store = FeishuTraceStore(db_path)
    except Exception as e:
        print(f"❌ 无法打开 trace DB: {e}")
        return 1

    # 直接查 SQLite 获取最近的 job_id
    import sqlite3
    conn = store._connect()
    rows = conn.execute(
        """SELECT job_id, phase, event_type, created_at
           FROM feishu_trace_events
           WHERE event_type IN ('event_accepted', 'job_failed', 'job_done')
           ORDER BY created_at DESC
           LIMIT 10;"""
    ).fetchall()
    conn.close()

    if not rows:
        print("  (无记录)")
        return 0

    print(f"\n📋  最近的 10 个 job (DB: {db_path})\n")
    for r in rows:
        import datetime
        dt = datetime.datetime.fromtimestamp(r["created_at"])
        print(f"  {dt.strftime('%m-%d %H:%M:%S')}  {r['job_id'][:12]}...  [{r['phase']}] {r['event_type']}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="飞书全链路追踪 — 查任意 job 的完整处理链路",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/feishu_trace.py --job-id abc123
  python tools/feishu_trace.py --job-id abc123 --json
  python tools/feishu_trace.py --job-id abc123 --verbose
  python tools/feishu_trace.py --recent
  python tools/feishu_trace.py --db-path /tmp/trace.db --job-id abc123
        """,
    )
    parser.add_argument("--db-path", help="trace DB 路径（自动查找）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument("--job-id", help="要查询的 job ID 或 trace ID")
    sub.add_argument("--recent", action="store_true", help="显示最近的 job")

    args = parser.parse_args()

    if args.recent:
        return cmd_recent(args)
    return cmd_trace(args)


if __name__ == "__main__":
    sys.exit(main())