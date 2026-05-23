from __future__ import annotations

from dataclasses import asdict

from memoryx.extraction import ExtractionMemory
from memoryx.storage import MemoryRecord
from memoryx.temporal import TemporalMemoryEngine
from memoryx.validation.conflict_resolver import ConflictResolver
from memoryx.validation.quarantine_manager import QuarantineManager


class MemorySafetyEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository
        self.quarantine = QuarantineManager()
        self.conflict = ConflictResolver()
        self.temporal = TemporalMemoryEngine(repository=repository)

    async def inspect_candidate(self, candidate: ExtractionMemory, existing_memories: list[MemoryRecord] | list[ExtractionMemory] | list[dict]) -> dict:
        existing = await self.repository.list_memories(limit=1000)
        normalized_existing = [
            ExtractionMemory(
                memory_type=str(item.get("memory_type", "FACT")),
                content=str(item.get("content", "")),
                importance_score=float(item.get("importance_score", 0.5)),
                confidence_score=float(item.get("confidence_score", 0.5)),
                entities=[],
                tags=[],
                scope=str(item.get("scope", "global")),
                timestamp=candidate.timestamp,
                source_message_id=item.get("source_message_id"),
                reasoning="",
            )
            for item in existing
        ]

        quarantine_report = self.quarantine.inspect(candidate)
        conflict = self.conflict.resolve(candidate, normalized_existing)
        flags = list(quarantine_report.flags)
        conflict_count = 1 if conflict is not None else 0

        if conflict is not None:
            flags.append("contradiction escalation")
            return {
                "action": "escalate" if not quarantine_report.should_quarantine else "quarantine",
                "flags": flags,
                "conflicts": conflict_count,
                "safety_score": max(0.0, 1.0 - quarantine_report.score),
            }

        if quarantine_report.should_quarantine:
            return {
                "action": "quarantine",
                "flags": flags,
                "conflicts": conflict_count,
                "safety_score": max(0.0, 1.0 - quarantine_report.score),
            }

        return {
            "action": "allow",
            "flags": flags,
            "conflicts": conflict_count,
            "safety_score": max(0.0, 1.0 - quarantine_report.score),
        }

    async def quarantine_stored_memory(self, *, memory_id: str, reason: str) -> dict:
        await self.repository.quarantine_memory(memory_id, reason)
        memory = await self.repository.get_memory(memory_id)
        if memory is not None:
            updated = MemoryRecord(
                memory_id=str(memory["memory_id"]),
                memory_type=str(memory["memory_type"]),
                content=str(memory["content"]),
                importance_score=float(memory.get("importance_score", 0.5)),
                confidence_score=float(memory.get("confidence_score", 0.5)),
                decay_score=float(memory.get("decay_score", 0.0)),
                recency_score=float(memory.get("recency_score", 0.0)),
                access_count=int(memory.get("access_count", 0)),
                checksum=str(memory.get("checksum", "")),
                superseded_by=memory.get("superseded_by"),
                valid_from=memory.get("valid_from"),
                valid_to=memory.get("valid_to"),
                active_state=str(memory.get("active_state", "active")),
                reinforcement_score=float(memory.get("reinforcement_score", 0.0)),
                safety_score=0.0,
                scope=str(memory.get("scope", "global")),
                source_message_id=memory.get("source_message_id"),
                entities_json=str(memory.get("entities_json", "[]")),
                tags_json=str(memory.get("tags_json", "[]")),
            )
            await self.repository.store_memory(updated)
        return {"memory_id": memory_id, "status": "quarantined", "reason": reason}

    async def rollback_view(self, *, memory_id: str) -> dict:
        versions = await self.temporal.timeline(memory_id=memory_id)
        return {
            "memory_id": memory_id,
            "versions": [asdict(version) for version in versions],
        }
