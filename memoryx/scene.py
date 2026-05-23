from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


class Scene:
    """场景块 — 关联记忆的高层聚合。"""
    def __init__(self, *, scene_id: str, title: str, description: str = "") -> None:
        self.scene_id = scene_id
        self.title = title
        self.description = description
        self.memory_ids: list[str] = []
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_markdown(self) -> str:
        """导出为 Markdown 格式。"""
        lines = [
            f"# Scene: {self.title}",
            f"ID: {self.scene_id}",
            f"Created: {self.created_at}",
            "",
        ]
        if self.description:
            lines.append(f"{self.description}\n")
        lines.append(f"## Memories ({len(self.memory_ids)})")
        for mid in self.memory_ids:
            lines.append(f"- `{mid}`")
        return "\n".join(lines)


class SceneEngine:
    """
    场景块聚合引擎 — 参考 TencentDB L2 Scene 设计。

    将相关记忆按主题 + 时间窗口聚类为场景块（Scene），
    作为介于 L1 原子记忆与 L3 角色画像之间的 L2 叙事层。
    """

    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def build_scenes(
        self,
        *,
        session_id: str | None = None,
        time_window_minutes: int = 60,
        max_scenes: int = 10,
    ) -> list[Scene]:
        """从活动记忆中构建场景块。"""
        memories = await self.repository.list_active_memories(limit=200)
        if session_id:
            memories = [m for m in memories if m.get("session_id") == session_id or True]

        # 按时间窗口聚类
        scenes: list[Scene] = []
        current_scene: list[dict[str, Any]] = []
        prev_time: str | None = None
        scene_index = 0

        for memory in memories:
            cur_time = str(memory.get("updated_at") or memory.get("created_at") or "")
            if prev_time is not None and self._time_diff_minutes(prev_time, cur_time) > time_window_minutes:
                if current_scene:
                    scenes.append(self._make_scene(current_scene, scene_index))
                    scene_index += 1
                    current_scene = []
            current_scene.append(memory)
            prev_time = cur_time

        if current_scene:
            scenes.append(self._make_scene(current_scene, scene_index))

        # 按重要性排序，取 top N
        for scene in scenes:
            scene.memory_ids.sort(key=lambda mid: self._get_score(mid, memories), reverse=True)
        scenes.sort(key=lambda s: len(s.memory_ids), reverse=True)
        return scenes[:max_scenes]

    async def export_markdown(self, scenes: list[Scene], output_dir) -> list[str]:
        """将场景块导出为 Markdown 文件。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        for scene in scenes:
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in scene.title)[:60]
            path = output_dir / f"scene-{safe_name}.md"
            path.write_text(scene.to_markdown(), encoding="utf-8")
            paths.append(str(path))
        return paths

    def _make_scene(self, memories: list[dict], index: int) -> Scene:
        contents = [str(m.get("content", "")) for m in memories if m.get("content")]
        title = contents[0][:60] if contents else f"Scene {index}"
        scene = Scene(scene_id=f"scene-{index}-{len(memories)}", title=title)
        scene.memory_ids = [str(m["memory_id"]) for m in memories]
        scene.description = self._describe_scene(contents)
        return scene

    def _describe_scene(self, contents: list[str]) -> str:
        """从内容中提炼场景描述。"""
        types = set()
        for c in contents:
            lowered = c.lower()
            if any(t in lowered for t in ("bug", "error", "fix", "fail")):
                types.add("debugging")
            elif any(t in lowered for t in ("deploy", "release", "rollback")):
                types.add("deployment")
            elif any(t in lowered for t in ("prefer", "like", "dislike")):
                types.add("preference")
        if types:
            return f"Scene contains: {', '.join(sorted(types))}"
        return ""

    def _time_diff_minutes(self, t1: str, t2: str) -> float:
        try:
            dt1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
            return abs((dt2 - dt1).total_seconds() / 60.0)
        except (ValueError, TypeError):
            return 0.0

    def _get_score(self, memory_id: str, memories: list[dict]) -> float:
        for m in memories:
            if m.get("memory_id") == memory_id:
                return float(m.get("importance_score", 0.0))
        return 0.0
