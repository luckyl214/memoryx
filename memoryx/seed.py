from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import MemoryRecord


class ConversationSeed:
    """
    批量导入历史对话 — 从 JSON/JSONL 文件中喂养记忆系统。
    参考 TencentDB 的 /seed 端点设计。
    """

    def __init__(self, *, repository, extraction_engine=None) -> None:
        self.repository = repository
        self.extraction_engine = extraction_engine

    async def from_json(self, path: Path, *, session_key: str = "imported") -> dict[str, Any]:
        """从 JSON 文件导入对话。"""
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return await self._process(data, session_key=session_key)

    async def from_jsonl(self, path: Path, *, session_key: str = "imported") -> dict[str, Any]:
        """从 JSONL 文件（每行一条 JSON）导入。"""
        sessions_processed = 0
        rounds_processed = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    result = await self._process(data, session_key=session_key)
                    sessions_processed += result.get("sessions_processed", 0)
                    rounds_processed += result.get("rounds_processed", 0)
                except json.JSONDecodeError:
                    continue
        return {"sessions_processed": sessions_processed, "rounds_processed": rounds_processed}

    async def from_memory_records(self, records: list[MemoryRecord]) -> int:
        """直接批量导入 MemoryRecord。"""
        return await self.repository.store_memories(records)

    async def _process(self, data: dict[str, Any], *, session_key: str) -> dict[str, Any]:
        sessions = data.get("sessions", [data] if isinstance(data, dict) and "messages" in data else [])
        sessions_processed = 0
        rounds_processed = 0
        for session in sessions:
            messages = session.get("messages", session.get("conversation", []))
            if not messages:
                continue
            session_id = str(session.get("id", session.get("session_id", session_key)))
            for msg in messages:
                role = str(msg.get("role", "user"))
                content = str(msg.get("content", ""))
                if not content:
                    continue
                record = MemoryRecord(
                    memory_id=__import__("uuid").uuid4().hex,
                    memory_type="EXPERIENCE",
                    content=content,
                    scope="imported",
                    source_message_id=session_id,
                )
                await self.repository.store_memory(record)
                rounds_processed += 1
            sessions_processed += 1
        return {"sessions_processed": sessions_processed, "rounds_processed": rounds_processed}
