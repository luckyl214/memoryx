from __future__ import annotations

import asyncio
from collections import Counter

from .models import ToolInteractionRecord


class ToolInteractionMemory:
    def __init__(self) -> None:
        self._records: list[ToolInteractionRecord] = []
        self._lock = asyncio.Lock()

    async def record(
        self,
        *,
        session_id: str,
        tool_name: str,
        action_type: str,
        command: str,
        success: bool,
        metadata: dict[str, object] | None = None,
    ) -> ToolInteractionRecord:
        record = ToolInteractionRecord(
            session_id=session_id,
            tool_name=tool_name,
            action_type=action_type,
            command=command,
            success=success,
            metadata=dict(metadata or {}),
        )
        async with self._lock:
            self._records.append(record)
        return record

    async def history(
        self,
        *,
        session_id: str,
        action_type: str | None = None,
        tool_name: str | None = None,
    ) -> list[ToolInteractionRecord]:
        async with self._lock:
            records = [record for record in self._records if record.session_id == session_id]
        if action_type is not None:
            records = [record for record in records if record.action_type == action_type]
        if tool_name is not None:
            records = [record for record in records if record.tool_name == tool_name]
        return records

    async def stats(self, *, session_id: str) -> dict[str, object]:
        records = await self.history(session_id=session_id)
        counter = Counter(record.tool_name for record in records)
        success = sum(1 for record in records if record.success)
        failure = len(records) - success
        return {
            "total": len(records),
            "success": success,
            "failure": failure,
            "by_tool": dict(counter),
        }

    async def replay(self, *, session_id: str) -> list[str]:
        records = await self.history(session_id=session_id)
        return [record.command for record in records]
