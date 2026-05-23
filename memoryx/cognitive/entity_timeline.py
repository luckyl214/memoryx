"""EntityTimelineEngine: time-ordered entity memory retrieval via entity_memory_links."""
from __future__ import annotations

from typing import Any


class EntityTimelineEngine:
    """Retrieve memories linked to an entity, ordered by time.

    Uses entity_memory_links for indexed lookups instead of metadata_json LIKE.
    """

    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def timeline(
        self,
        *,
        entity_id: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ["eml.entity_id = ?", "eml.active_state = 'active'", "m.active_state = 'active'"]
        params: list[Any] = [entity_id]

        if start:
            where.append("COALESCE(eml.valid_from, m.valid_from, m.created_at) >= ?")
            params.append(start)
        if end:
            where.append("COALESCE(eml.valid_from, m.valid_from, m.created_at) <= ?")
            params.append(end)

        sql = f"""
            SELECT m.*, eml.relation_type, eml.confidence_score AS link_confidence
            FROM entity_memory_links eml
            JOIN memories m ON m.id = eml.memory_id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(eml.valid_from, m.valid_from, m.created_at) ASC
            LIMIT ?;
        """
        params.append(limit)
        rows = await self.repository.db.fetchall(sql, params)
        return [dict(r) for r in rows]

    async def link(
        self,
        *,
        entity_id: str,
        memory_id: str,
        relation_type: str = "mentioned",
        confidence_score: float = 0.5,
    ) -> None:
        await self.repository.db.execute(
            """INSERT OR REPLACE INTO entity_memory_links(
                entity_id, memory_id, relation_type, confidence_score, active_state,
                created_at, valid_from
            ) VALUES (?,?,?,?,?,datetime('now'),datetime('now'))""",
            (entity_id, memory_id, relation_type, confidence_score, "active"),
        )
