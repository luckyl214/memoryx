from __future__ import annotations

from datetime import datetime

from .models import TemporalState


class TemporalMemoryEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def history(self, memory_id: str) -> list[TemporalState]:
        rows = await self.repository.db.fetchall(
            "SELECT version_number, content FROM memory_versions WHERE memory_id = ? ORDER BY version_number ASC;",
            (memory_id,),
        )
        current = await self.repository.get_memory(memory_id)
        states = [
            TemporalState(
                memory_id=memory_id,
                content=str(row["content"]),
                version_number=int(row["version_number"]),
            )
            for row in rows
        ]
        if current and states:
            states[-1].valid_from = current.get("valid_from")
            states[-1].valid_to = current.get("valid_to")
            states[-1].active_state = int(current.get("active_state", 1))
            states[-1].superseded_by = current.get("superseded_by")
        elif current and not states:
            states.append(
                TemporalState(
                    memory_id=memory_id,
                    content=str(current.get("content", "")),
                    version_number=1,
                    valid_from=current.get("valid_from"),
                    valid_to=current.get("valid_to"),
                    active_state=int(current.get("active_state", 1)),
                    superseded_by=current.get("superseded_by"),
                )
            )
        return states

    async def timeline(self, memory_id: str) -> list[TemporalState]:
        states = await self.history(memory_id)
        current = await self.repository.get_memory(memory_id)
        if not states:
            return states
        if current and len(states) >= 2 and current.get("valid_from"):
            boundary = str(current["valid_from"])
            states[-2].valid_to = boundary
            if states[-2].valid_from is None:
                states[-2].valid_from = boundary
        return states

    async def at_time(self, memory_id: str, point_in_time: str) -> TemporalState | None:
        states = await self.timeline(memory_id)
        if not states:
            return None
        query_dt = self._parse_dt(point_in_time)
        current = await self.repository.get_memory(memory_id)
        current_valid_from = self._parse_dt(str(current.get("valid_from"))) if current and current.get("valid_from") else None
        if len(states) >= 2 and current_valid_from and query_dt < current_valid_from:
            return states[-2]
        last = states[-1]
        valid_from = self._parse_dt(last.valid_from) if last.valid_from else None
        valid_to = self._parse_dt(last.valid_to) if last.valid_to else None
        if (valid_from is None or query_dt >= valid_from) and (valid_to is None or query_dt <= valid_to):
            return last
        return states[0]

    async def supersede(self, memory_id: str, superseded_by: str) -> None:
        await self.repository.supersede_memory(memory_id, superseded_by)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime:
        if not value:
            return datetime.min
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
