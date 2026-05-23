from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class PalaceWing:
    """翼 — 最高层级，对应项目/人/工作空间。"""
    wing_id: str
    name: str
    description: str = ""
    room_count: int = 0
    created_at: str = ""


@dataclass(slots=True)
class PalaceRoom:
    """房间 — 中层，对应话题/日期/会话。"""
    room_id: str
    wing_id: str
    name: str
    description: str = ""
    drawer_count: int = 0
    created_at: str = ""


@dataclass(slots=True)
class PalaceDrawer:
    """抽屉 — 最低层，对应字面原文分块。"""
    drawer_id: str
    room_id: str
    memory_id: str | None = None
    content: str = ""
    source: str = "conversation"
    line_start: int = 0
    line_end: int = 0
    created_at: str = ""
