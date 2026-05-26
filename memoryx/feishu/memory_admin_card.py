"""P1: 飞书记忆管理卡片 — 优化版（分栏布局 + 按钮交互）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _cst_now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


TYPE_META = {
    "EPISODIC":    {"label": "会话记忆",  "emoji": "💬", "color": "blue"},
    "FACT":        {"label": "事实知识",  "emoji": "📌", "color": "green"},
    "PERSONA":     {"label": "用户画像",  "emoji": "👤", "color": "purple"},
    "OBSERVATION": {"label": "观察日志",  "emoji": "📝", "color": "grey"},
    "LESSON":      {"label": "经验教训",  "emoji": "💡", "color": "indigo"},
}


def _bar_pct(pct: float, width: int = 8) -> str:
    filled = max(1, int(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


async def collect_memory_stats(repository) -> dict:
    rows = await repository.db.fetchall(
        """SELECT memory_type, active_state, COUNT(*) as cnt
           FROM memories GROUP BY memory_type, active_state
           ORDER BY cnt DESC;""", ()
    )
    by_type: dict[str, dict] = {}
    total_active = 0
    total_all = 0
    for r in rows:
        mtype = r["memory_type"]
        if mtype not in by_type:
            by_type[mtype] = {"total": 0, "active": 0}
        cnt = r["cnt"]
        by_type[mtype]["total"] += cnt
        total_all += cnt
        if r["active_state"] == "active":
            by_type[mtype]["active"] += cnt
            total_active += cnt
    return {
        "total": total_all,
        "active": total_active,
        "by_type": dict(sorted(by_type.items(), key=lambda x: x[1]["total"], reverse=True)),
    }


async def collect_recent_memories(repository, limit: int = 5) -> list[dict]:
    rows = await repository.db.fetchall(
        """SELECT id, memory_type, substr(content,1,80) as preview, created_at
           FROM memories ORDER BY created_at DESC LIMIT ?;""", (limit,)
    )
    return [{"id": r["id"], "type": r["memory_type"], "preview": r["preview"], "created_at": r["created_at"]} for r in rows]


async def collect_lancedb_stats(vector_store) -> dict | None:
    if vector_store is None:
        return None
    try:
        import numpy as np
        vec = np.random.randn(4096).astype(np.float32).tolist()
        results = await vector_store.search(vec, limit=500)
        return {"vector_count": len(results), "enabled": True}
    except Exception:
        return {"enabled": False}


def build_stats_bar(elements: list[dict], by_type: dict[str, dict], total: int) -> None:
    """插入类型分布柱状图——用 column_set + 短 md 实现视觉条。"""
    items = []
    colors = {
        "OBSERVATION": "#808080",
        "EPISODIC": "#3370FF",
        "FACT": "#00B42A",
        "PERSONA": "#722ED1",
        "LESSON": "#F77234",
    }
    for mtype, data in by_type.items():
        meta = TYPE_META.get(mtype, {"emoji": "📄", "label": mtype})
        pct = data["total"] / total * 100 if total > 0 else 0
        color = colors.get(mtype, "#3370FF")
        items.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{
                "tag": "markdown",
                "content": (
                    f"**{meta['emoji']} {meta['label']}**\n"
                    f"**{data['total']}** 条（活跃 {data['active']}）\n"
                    f"`{_bar_pct(pct, 8)}` {pct:.0f}%"
                ),
            }],
        })
    
    # 两列一组，每列放两个
    rows = []
    for i in range(0, len(items), 2):
        row = items[i:i+2]
        if len(row) == 1:
            row.append({"tag": "column", "width": "weighted", "weight": 1, "elements": []})
        rows.append({
            "tag": "column_set",
            "flex_mode": "bisect",
            "background_style": "default",
            "columns": row,
        })
    elements.extend(rows)


def build_recent_section(recent: list[dict]) -> list[dict]:
    """最近记忆——用 field 样式更紧凑。"""
    if not recent:
        return [{"tag": "markdown", "content": "暂无记忆"}]
    
    elements = []
    for r in recent:
        meta = TYPE_META.get(r["type"], {"emoji": "📄", "label": r["type"]})
        created = r["created_at"]
        if isinstance(created, str):
            created = created[:19].replace("T", " ")
        elements.append({
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**{meta['emoji']} {meta['label']}**"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"`{created}`"}},
            ],
        })
        elements.append({
            "tag": "markdown",
            "content": f"  {r['preview'][:60]}...",
        })
    return elements


def build_card(stats: dict, recent: list[dict], lancedb: dict | None) -> dict[str, Any]:
    """构建优化版飞书记忆管理卡片。"""
    now = _cst_now()
    
    elements: list[dict[str, Any]] = []
    
    # ── 概览行 ──
    overview_items = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{"tag": "markdown", "content": f"**📊 总记忆**\n**{stats['total']}** 条"}],
        },
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{"tag": "markdown", "content": f"**✅ 活跃**\n**{stats['active']}** 条"}],
        },
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{"tag": "markdown", "content": f"**🔍 向量检索**\n{'✅ 已启用' if lancedb and lancedb.get('enabled') else '❌ 未启用'}"}],
        },
    ]
    elements.append({"tag": "column_set", "flex_mode": "bisect", "columns": overview_items})
    elements.append({"tag": "hr"})

    # ── 类型分布 ──
    elements.append({"tag": "markdown", "content": "**📈 记忆类型分布**"})
    build_stats_bar(elements, stats["by_type"], stats["total"])
    elements.append({"tag": "hr"})

    # ── 最近记忆 ──
    elements.append({"tag": "markdown", "content": "**🕐 最近记忆**"})
    elements.extend(build_recent_section(recent))
    elements.append({"tag": "hr"})

    # ── 操作按钮 ──
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔄 刷新"},
                "type": "primary",
                "value": {"action": "refresh_memory_stats"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📋 查看全部"},
                "type": "default",
                "value": {"action": "list_all_memories"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔍 搜索"},
                "type": "default",
                "value": {"action": "search_memories"},
            },
        ],
    })

    # ── 底部标注 ──
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"MemoryX v1.1.0 · LanceDB {lancedb.get('vector_count', 0) if lancedb else 0} 条向量 · {now}"},
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧠 MemoryX 记忆管理"},
            "template": "blue",
        },
        "elements": elements,
    }