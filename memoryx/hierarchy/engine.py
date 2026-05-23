from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class MemoryTier(StrEnum):
    WORKING = "working"
    SHORT_TERM_EPISODIC = "short_term_episodic"
    LONG_TERM_SEMANTIC = "long_term_semantic"
    CONSOLIDATED_KNOWLEDGE = "consolidated_knowledge"
    ARCHIVE = "archive"


@dataclass(slots=True)
class MemoryMigrationReport:
    migrated_counts: dict[MemoryTier, int] = field(default_factory=dict)
    tier_assignments: dict[str, MemoryTier] = field(default_factory=dict)


class HierarchicalMemoryManager:
    def __init__(self, *, repository, working_memory) -> None:
        self.repository = repository
        self.working_memory = working_memory

    async def classify_long_term_tiers(self, *, limit: int = 1000) -> dict[str, MemoryTier]:
        memories = await self.repository.list_memories(limit=limit)
        return {str(memory["memory_id"]): self._classify_record(memory) for memory in memories}

    async def migrate_tiers(self) -> MemoryMigrationReport:
        memories = await self.repository.list_memories(limit=1000)
        report = MemoryMigrationReport()
        for memory in memories:
            memory_id = str(memory["memory_id"])
            tier = self._classify_record(memory)
            report.tier_assignments[memory_id] = tier
            if tier == MemoryTier.ARCHIVE and int(memory.get("active_state", 1)) == 1:
                await self._archive_memory(memory)
                report.migrated_counts[tier] = report.migrated_counts.get(tier, 0) + 1
        return report

    async def retrieve_tier(self, tier: MemoryTier, *, session_id: str | None = None, limit: int = 10) -> list[dict]:
        if tier == MemoryTier.WORKING:
            if not session_id:
                return []
            state = await self.working_memory.get_state(session_id)
            if state is None:
                return []
            return [
                {
                    "tier": MemoryTier.WORKING,
                    "session_id": state.session_id,
                    "current_task": state.current_task,
                    "reasoning_chain": list(state.reasoning_chain),
                    "active_todos": list(state.active_todos),
                }
            ]

        if tier == MemoryTier.SHORT_TERM_EPISODIC:
            if session_id:
                rows = await self.repository.db.fetchall(
                    "SELECT episodic_id, session_id, title, content, importance_score, created_at FROM episodic_memories WHERE session_id = ? ORDER BY importance_score DESC, created_at DESC LIMIT ?;",
                    (session_id, limit),
                )
            else:
                rows = await self.repository.db.fetchall(
                    "SELECT episodic_id, session_id, title, content, importance_score, created_at FROM episodic_memories ORDER BY importance_score DESC, created_at DESC LIMIT ?;",
                    (limit,),
                )
            return [dict(row, tier=MemoryTier.SHORT_TERM_EPISODIC) for row in rows]

        if tier == MemoryTier.ARCHIVE:
            rows = await self.repository.db.fetchall(
                "SELECT memory_id, content, archived_at FROM archived_memories ORDER BY archived_at DESC LIMIT ?;",
                (limit,),
            )
            return [dict(row, tier=MemoryTier.ARCHIVE) for row in rows]

        memories = await self.repository.list_active_memories(limit=1000)
        selected = [memory for memory in memories if self._classify_record(memory) == tier]
        return [dict(memory, tier=tier) for memory in selected[:limit]]

    async def retrieve(self, *, query: str, tiers: list[MemoryTier], limit: int = 10) -> list[dict]:
        lowered_query = query.lower()
        results: list[dict] = []
        for tier in tiers:
            candidates = await self.retrieve_tier(tier, limit=limit)
            for item in candidates:
                text = f"{item.get('content', '')} {item.get('title', '')} {item.get('current_task', '')}".lower()
                if not lowered_query or any(token in text for token in lowered_query.split()):
                    results.append(item)
                    if len(results) >= limit:
                        return results
        return results

    def _classify_record(self, memory: dict) -> MemoryTier:
        decay = float(memory.get("decay_score", 0.0) or 0.0)
        access_count = int(memory.get("access_count", 0) or 0)
        importance = float(memory.get("importance_score", 0.0) or 0.0)
        memory_type = str(memory.get("memory_type", "")).upper()
        active_state = int(memory.get("active_state", 1) or 0)

        if active_state == 0 or (decay >= 0.9 and access_count == 0):
            return MemoryTier.ARCHIVE
        if memory_type == "EPISODIC":
            return MemoryTier.SHORT_TERM_EPISODIC
        if importance >= 0.85 or access_count >= 3:
            return MemoryTier.LONG_TERM_SEMANTIC
        return MemoryTier.CONSOLIDATED_KNOWLEDGE

    async def _archive_memory(self, memory: dict) -> None:
        memory_id = str(memory["memory_id"])
        await self.repository.db.execute(
            "INSERT OR IGNORE INTO archived_memories(archive_id, memory_id, content, archived_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP);",
            (f"archive-{memory_id}-{uuid4().hex}", memory_id, str(memory.get("content", ""))),
        )
        await self.repository.rollback_memory(memory_id)
