from __future__ import annotations

from collections import defaultdict
from uuid import uuid4


class ConsolidationEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def summarize_session(self, session_id: str) -> str:
        memories = await self.repository.list_active_memories(limit=20)
        selected = [item["content"] for item in memories[:3]]
        summary = " | ".join(selected) if selected else "No significant memories captured."
        await self.repository.add_session_summary(session_id=session_id, summary=summary, source_count=len(selected))
        return summary

    async def apply_decay(self) -> int:
        memories = await self.repository.list_memories(limit=1000)
        updated = 0
        for memory in memories:
            access_count = int(memory.get("access_count", 0))
            importance = float(memory.get("importance_score", 0.0))
            current_decay = float(memory.get("decay_score", 0.0))
            if access_count <= 1 and importance < 0.6:
                new_decay = min(1.0, current_decay + 0.15)
                await self.repository.db.execute(
                    "UPDATE memories SET decay_score = ?, updated_at = CURRENT_TIMESTAMP WHERE memory_id = ?;",
                    (new_decay, memory["memory_id"]),
                )
                updated += 1
        return updated

    async def archive_cold_memories(self) -> int:
        memories = await self.repository.list_memories(limit=1000)
        archived = 0
        for memory in memories:
            decay = float(memory.get("decay_score", 0.0))
            access_count = int(memory.get("access_count", 0))
            if decay >= 0.9 and access_count == 0 and int(memory.get("active_state", 1)) == 1:
                await self.repository.db.execute(
                    "INSERT INTO archived_memories(archive_id, memory_id, content, archived_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP);",
                    (f"archive-{memory['memory_id']}", memory["memory_id"], memory["content"]),
                )
                await self.repository.rollback_memory(memory["memory_id"])
                archived += 1
        return archived

    async def reinforce_memories(self) -> int:
        memories = await self.repository.list_active_memories(limit=1000)
        reinforced = 0
        for memory in memories:
            importance = float(memory.get("importance_score", 0.0))
            access_count = int(memory.get("access_count", 0))
            current_score = float(memory.get("reinforcement_score", 0.0))
            if importance >= 0.85 or access_count >= 3:
                new_score = min(1.0, current_score + 0.15)
                await self.repository.db.execute(
                    "UPDATE memories SET reinforcement_score = ?, updated_at = CURRENT_TIMESTAMP WHERE memory_id = ?;",
                    (new_score, memory["memory_id"]),
                )
                await self.repository.db.execute(
                    "INSERT INTO reinforcement_events(reinforcement_id, memory_id, reinforcement_type, score_delta, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
                    (uuid4().hex, memory["memory_id"], "consolidation_reinforcement", 0.15),
                )
                reinforced += 1
        return reinforced

    async def merge_duplicates(self) -> int:
        memories = await self.repository.list_active_memories(limit=1000)
        by_content: dict[str, list[dict]] = defaultdict(list)
        for memory in memories:
            by_content[str(memory.get("content", "")).strip().lower()].append(memory)

        merged = 0
        for group in by_content.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda item: float(item.get("importance_score", 0.0)), reverse=True)
            primary = ordered[0]
            for duplicate in ordered[1:]:
                await self.repository.supersede_memory(duplicate["memory_id"], primary["memory_id"])
                merged += 1
        return merged
