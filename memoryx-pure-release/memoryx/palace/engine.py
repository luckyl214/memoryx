from __future__ import annotations

import json
from collections import deque
from typing import Any
from uuid import uuid4

from .models import PalaceDrawer, PalaceRoom, PalaceWing


class PalaceEngine:
    """
    Palace 引擎 — 层次化可导航记忆存储。

    参考 MemPalace 的 Wing→Room→Drawer 设计。
    记忆不仅被搜索，还可以被浏览导航。
    """

    def __init__(self, *, repository) -> None:
        self.repository = repository

    # ---- Wing 操作 ----

    async def ensure_wing(self, name: str, description: str = "") -> PalaceWing:
        """确保翼存在，不存在则创建。"""
        row = await self.repository.db.fetchone(
            "SELECT wing_id, name, description, created_at FROM palace_wings WHERE name = ?;",
            (name,),
        )
        if row:
            return PalaceWing(wing_id=str(row["wing_id"]), name=str(row["name"]),
                              description=str(dict(row).get("description", "")),
                              created_at=str(dict(row).get("created_at", "")))
        wing_id = uuid4().hex
        await self.repository.db.execute(
            "INSERT INTO palace_wings(wing_id, name, description, created_at, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (wing_id, name, description),
        )
        return PalaceWing(wing_id=wing_id, name=name, description=description)

    async def list_wings(self) -> list[PalaceWing]:
        """列出所有翼。"""
        rows = await self.repository.db.fetchall(
            "SELECT w.wing_id, w.name, w.description, w.created_at, "
            "(SELECT COUNT(*) FROM palace_rooms r WHERE r.wing_id = w.wing_id) AS room_count "
            "FROM palace_wings w ORDER BY w.name ASC;"
        )
        return [PalaceWing(wing_id=str(r["wing_id"]), name=str(r["name"]),
                           description=str(dict(r).get("description", "")),
                           room_count=int(dict(r).get("room_count", 0)),
                           created_at=str(dict(r).get("created_at", ""))) for r in rows]

    # ---- Room 操作 ----

    async def ensure_room(self, wing_id: str, name: str, description: str = "") -> PalaceRoom:
        """确保房间存在。"""
        row = await self.repository.db.fetchone(
            "SELECT room_id, wing_id, name, description, created_at FROM palace_rooms "
            "WHERE wing_id = ? AND name = ?;",
            (wing_id, name),
        )
        if row:
            return PalaceRoom(room_id=str(row["room_id"]), wing_id=str(row["wing_id"]),
                              name=str(row["name"]), description=str(dict(row).get("description", "")),
                              created_at=str(dict(row).get("created_at", "")))
        room_id = uuid4().hex
        await self.repository.db.execute(
            "INSERT INTO palace_rooms(room_id, wing_id, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (room_id, wing_id, name, description),
        )
        return PalaceRoom(room_id=room_id, wing_id=wing_id, name=name, description=description)

    async def list_rooms(self, wing_id: str) -> list[PalaceRoom]:
        """列出某翼下的所有房间。"""
        rows = await self.repository.db.fetchall(
            "SELECT r.room_id, r.wing_id, r.name, r.description, r.created_at, "
            "(SELECT COUNT(*) FROM palace_drawers d WHERE d.room_id = r.room_id) AS drawer_count "
            "FROM palace_rooms r WHERE r.wing_id = ? ORDER BY r.created_at DESC;",
            (wing_id,),
        )
        return [PalaceRoom(room_id=str(r["room_id"]), wing_id=str(r["wing_id"]),
                           name=str(r["name"]), description=str(dict(r).get("description", "")),
                           drawer_count=int(dict(r).get("drawer_count", 0)),
                           created_at=str(dict(r).get("created_at", ""))) for r in rows]

    # ---- Drawer 操作 ----

    async def add_drawer(
        self,
        room_id: str,
        content: str,
        *,
        memory_id: str | None = None,
        source: str = "conversation",
    ) -> PalaceDrawer:
        """向房间添加入字面抽屉。"""
        drawer_id = uuid4().hex
        content_lines = content.split("\n")
        line_end = len(content_lines)
        await self.repository.db.execute(
            "INSERT INTO palace_drawers(drawer_id, room_id, memory_id, content, source, line_start, line_end, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (drawer_id, room_id, memory_id, content, source, 0, line_end),
        )
        return PalaceDrawer(drawer_id=drawer_id, room_id=room_id, memory_id=memory_id,
                            content=content, source=source, line_end=line_end)

    async def list_drawers(self, room_id: str) -> list[PalaceDrawer]:
        """列出某房间的所有抽屉。"""
        rows = await self.repository.db.fetchall(
            "SELECT drawer_id, room_id, memory_id, content, source, line_start, line_end, created_at "
            "FROM palace_drawers WHERE room_id = ? ORDER BY created_at ASC;",
            (room_id,),
        )
        return [PalaceDrawer(drawer_id=str(r["drawer_id"]), room_id=str(r["room_id"]),
                              memory_id=str(r["memory_id"]) if dict(r).get("memory_id") else None,
                              content=str(r["content"]), source=str(dict(r).get("source", "conversation")),
                              line_start=int(dict(r).get("line_start", 0)), line_end=int(dict(r).get("line_end", 0)),
                              created_at=str(dict(r).get("created_at", ""))) for r in rows]

    async def get_drawer(self, drawer_id: str) -> PalaceDrawer | None:
        """获取单个抽屉。"""
        row = await self.repository.db.fetchone(
            "SELECT drawer_id, room_id, memory_id, content, source, line_start, line_end, created_at "
            "FROM palace_drawers WHERE drawer_id = ?;",
            (drawer_id,),
        )
        if not row:
            return None
        return PalaceDrawer(drawer_id=str(row["drawer_id"]), room_id=str(row["room_id"]),
                            memory_id=str(row["memory_id"]) if dict(row).get("memory_id") else None,
                            content=str(row["content"]), source=str(dict(row).get("source", "conversation")),
                            line_start=int(dict(row).get("line_start", 0)), line_end=int(dict(row).get("line_end", 0)),
                            created_at=str(dict(row).get("created_at", "")))

    # ---- 隧道 & 导航 ----

    async def add_tunnel(self, source_wing_id: str, target_wing_id: str, weight: float = 1.0) -> None:
        """在两个翼之间创建隧道。"""
        await self.repository.db.execute(
            "INSERT OR REPLACE INTO palace_tunnels(tunnel_id, source_wing_id, target_wing_id, weight, created_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (uuid4().hex, source_wing_id, target_wing_id, weight),
        )

    async def traverse(self, wing_name: str, depth: int = 2) -> list[dict]:
        """从某个翼开始图遍历，返回相邻翼。"""
        results: list[dict] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()

        start = await self.repository.db.fetchone(
            "SELECT wing_id, name, description FROM palace_wings WHERE name = ?;", (wing_name,))
        if not start:
            return results
        queue.append((str(start["wing_id"]), 0))

        while queue:
            current_id, level = queue.popleft()
            if current_id in visited or level > depth:
                continue
            visited.add(current_id)
            wing = await self.repository.db.fetchone(
                "SELECT wing_id, name, description FROM palace_wings WHERE wing_id = ?;", (current_id,))
            if wing:
                results.append({"wing_id": str(wing["wing_id"]), "name": str(wing["name"]),
                                "description": str(wing["description"]) if wing["description"] else "", "depth": level})
            for direction in ["source_wing_id", "target_wing_id"]:
                other = "target_wing_id" if direction == "source_wing_id" else "source_wing_id"
                edges = await self.repository.db.fetchall(
                    f"SELECT {other} AS neighbor_id FROM palace_tunnels WHERE {direction} = ? ORDER BY weight DESC;",
                    (current_id,),
                )
                for edge in edges:
                    queue.append((str(edge["neighbor_id"]), level + 1))
        return results

    # ---- 搜索 ----

    async def search_wing(self, wing_name: str, query: str) -> list[PalaceDrawer]:
        """在指定翼内搜索所有抽屉。"""
        query_lower = query.lower()
        wing = await self.repository.db.fetchone(
            "SELECT wing_id FROM palace_wings WHERE name = ?;", (wing_name,))
        if not wing:
            return []
        wing_id = str(wing["wing_id"])
        rows = await self.repository.db.fetchall(
            "SELECT d.drawer_id, d.room_id, d.memory_id, d.content, d.source, d.line_start, d.line_end, d.created_at "
            "FROM palace_drawers d "
            "JOIN palace_rooms r ON r.room_id = d.room_id "
            "WHERE r.wing_id = ? AND lower(d.content) LIKE ? "
            "ORDER BY d.created_at DESC LIMIT 20;",
            (wing_id, f"%{query_lower}%"),
        )
        return [PalaceDrawer(drawer_id=str(r["drawer_id"]), room_id=str(r["room_id"]),
                              memory_id=str(r["memory_id"]) if dict(r).get("memory_id") else None,
                              content=str(r["content"]), source=str(dict(r).get("source", "conversation")),
                              line_start=int(dict(r).get("line_start", 0)), line_end=int(dict(r).get("line_end", 0)),
                              created_at=str(dict(r).get("created_at", ""))) for r in rows]


class PalaceNavigator:
    """Palace 导航器 — 提供高层遍历 API。"""

    def __init__(self, engine: PalaceEngine) -> None:
        self.engine = engine

    async def walk_to(self, wing_name: str, room_name: str | None = None) -> list[str]:
        """导航到指定位置，返回内容列表。"""
        wing = await self.engine.repository.db.fetchone(
            "SELECT wing_id FROM palace_wings WHERE name = ?;", (wing_name,))
        if not wing:
            return []
        if room_name:
            room = await self.engine.repository.db.fetchone(
                "SELECT room_id FROM palace_rooms WHERE wing_id = ? AND name = ?;",
                (str(wing["wing_id"]), room_name),
            )
            if not room:
                return []
            drawers = await self.engine.list_drawers(str(room["room_id"]))
        else:
            wings = await self.engine.list_wings()
            return [f"Wing: {w.name} ({w.room_count} rooms)" for w in wings]
        return [f"[L{d.line_start}-L{d.line_end}] {d.content}" for d in drawers]
