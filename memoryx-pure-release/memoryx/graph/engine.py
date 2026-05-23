from __future__ import annotations

import json
from collections import deque


class EntityGraphEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def ensure_entity(self, entity_name: str, entity_type: str = "unknown") -> str:
        row = await self.repository.db.fetchone(
            "SELECT id AS entity_id FROM entities WHERE lower(name) = lower(?) AND entity_type = ? LIMIT 1;",
            (entity_name, entity_type),
        )
        if row:
            return str(row["entity_id"])
        return await self.repository.add_entity(entity_name=entity_name, entity_type=entity_type)

    async def ingest_memory_entities(self, memory_id: str) -> int:
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return 0
        entity_names = json.loads(memory.get("entities_json", "[]") or "[]")
        if not entity_names:
            return 0

        created_ids: list[str] = []
        for name in entity_names:
            entity_type = self._guess_type(str(name), str(memory.get("scope", "global")))
            created_ids.append(await self.ensure_entity(str(name), entity_type=entity_type))

        root_id = created_ids[0]
        for target_id in created_ids[1:]:
            await self.repository.add_relation(root_id, target_id, "related_to", 0.7)
        return len(created_ids)

    async def neighbors(self, entity_name: str) -> list[dict]:
        row = await self.repository.db.fetchone(
            "SELECT id AS entity_id FROM entities WHERE lower(name) = lower(?) LIMIT 1;",
            (entity_name,),
        )
        if not row:
            return []
        entity_id = str(row["entity_id"])
        rows = await self.repository.db.fetchall(
            """
            SELECT e.id AS entity_id, e.name AS entity_name, e.entity_type, r.relation_type, r.confidence_score AS weight
            FROM relations r
            JOIN entities e ON e.id = r.target_entity_id
            WHERE r.source_entity_id = ?
            ORDER BY r.confidence_score DESC, e.name ASC;
            """,
            (entity_id,),
        )
        return [dict(item) for item in rows]

    async def traverse(self, entity_name: str, depth: int = 2) -> list[dict]:
        start = await self.repository.db.fetchone(
            "SELECT id AS entity_id, name AS entity_name, entity_type FROM entities WHERE lower(name) = lower(?) LIMIT 1;",
            (entity_name,),
        )
        if not start:
            return []

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(str(start["entity_id"]), 0)])
        results: list[dict] = []

        while queue:
            current_id, level = queue.popleft()
            if current_id in visited or level > depth:
                continue
            visited.add(current_id)
            entity = await self.repository.db.fetchone(
                "SELECT id AS entity_id, name AS entity_name, entity_type FROM entities WHERE id = ?;",
                (current_id,),
            )
            if entity:
                results.append(dict(entity))
            edges = await self.repository.db.fetchall(
                "SELECT target_entity_id FROM relations WHERE source_entity_id = ? ORDER BY confidence_score DESC;",
                (current_id,),
            )
            for edge in edges:
                queue.append((str(edge["target_entity_id"]), level + 1))
        return results

    async def project_graph(self) -> list[dict]:
        rows = await self.repository.db.fetchall(
            "SELECT id AS entity_id, name AS entity_name, entity_type FROM entities WHERE entity_type IN ('project', 'technology') ORDER BY name ASC;"
        )
        return [dict(item) for item in rows]

    async def disambiguate(self, name: str, context: str = "") -> list[dict]:
        """实体消歧 — 查找同名实体的不同上下文。"""
        query = "SELECT id AS entity_id, name AS entity_name, entity_type, metadata_json FROM entities WHERE lower(name) = lower(?);"
        rows = await self.repository.db.fetchall(query, (name,))
        results = [dict(r) for r in rows]
        if context and len(results) > 1:
            scored = []
            for r in results:
                meta = r.get("metadata_json", "{}")
                score = 1.0 if context.lower() in meta.lower() else 0.0
                scored.append((score, r))
            scored.sort(key=lambda x: -x[0])
            results = [r for _, r in scored]
        return results

    async def resolve_entity(self, name: str, context: str = "") -> dict | None:
        """解析实体：优先返回与上下文匹配的，否则返回最新的。"""
        candidates = await self.disambiguate(name, context=context)
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _guess_type(name: str, scope: str) -> str:
        lowered = name.lower()
        if scope == "project":
            if any(token in lowered for token in ["python", "sqlite", "lancedb", "EmbeddingModel", "deepseek"]):
                return "technology"
            return "project"
        return "unknown"
