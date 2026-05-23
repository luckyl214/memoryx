"""P4: SQLite BFS 图检索器 —— 实体-关系图 2-hop 遍历。

使用 entities / relations 表进行图检索。
输出 score、paths、entities。
作为 graph 通道融合进 HybridRetrievalEngine。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphPath:
    """单条 BFS 路径。"""
    entity_ids: list[str]
    relation_types: list[str]
    hop_count: int
    terminal_memory_ids: list[str] = field(default_factory=list)


@dataclass
class GraphResult:
    """图检索结果。"""
    memory_id: str
    score: float
    paths: list[GraphPath] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


class GraphRetriever:
    """SQLite BFS 图检索器。

    默认 2-hop，从起始实体出发沿 relations 表遍历。
    """

    def __init__(
        self,
        *,
        repository,
        max_hops: int = 2,
        max_paths: int = 20,
    ) -> None:
        self.repository = repository
        self.max_hops = max_hops
        self.max_paths = max_paths

    async def retrieve(
        self,
        entity_names: list[str],
        *,
        limit: int = 10,
    ) -> list[GraphResult]:
        """从实体名称出发，BFS 遍历图，返回关联的记忆。

        Args:
            entity_names: 起始实体名称列表
            limit: 返回结果数量上限
        """
        # Resolve entity names → entity IDs
        start_ids = await self._resolve_entities(entity_names)
        if not start_ids:
            return []

        # BFS
        paths = await self._bfs(start_ids)

        # Collect terminal memory IDs
        results: dict[str, GraphResult] = {}
        for path in paths:
            for mem_id in path.terminal_memory_ids:
                if mem_id not in results:
                    results[mem_id] = GraphResult(
                        memory_id=mem_id,
                        score=0.0,
                        paths=[],
                    )
                results[mem_id].paths.append(path)
                results[mem_id].entities = list(set(
                    results[mem_id].entities + path.entity_ids
                ))

        # Score: more paths & shorter hops = higher
        for r in results.values():
            r.score = sum(1.0 / (p.hop_count + 1) for p in r.paths) / self.max_paths

        sorted_results = sorted(results.values(), key=lambda r: r.score, reverse=True)
        return sorted_results[:limit]

    async def _resolve_entities(self, names: list[str]) -> list[str]:
        normalized = [n.lower().strip() for n in names]
        placeholders = ",".join("?" for _ in normalized)
        rows = await self.repository.db.fetchall(
            f"SELECT id FROM entities WHERE LOWER(normalized_name) IN ({placeholders}) AND active_state = 'active';",
            tuple(normalized),
        )
        return [row["id"] for row in rows]

    async def _bfs(self, start_ids: list[str]) -> list[GraphPath]:
        """BFS 遍历，最多 max_hops 跳。"""
        all_paths: list[GraphPath] = []

        for start_id in start_ids:
            visited: set[str] = {start_id}
            queue: deque[tuple[str, list[str], list[str], int]] = deque()
            queue.append((start_id, [start_id], [], 0))

            while queue and len(all_paths) < self.max_paths:
                current, entity_path, rel_types, hops = queue.popleft()
                if hops >= self.max_hops:
                    continue

                # Find outgoing relations
                rows = await self.repository.db.fetchall(
                    """
                    SELECT target_entity_id, relation_type
                    FROM relations
                    WHERE source_entity_id = ? AND active_state = 'active'
                    ORDER BY confidence_score DESC
                    LIMIT 50;
                    """,
                    (current,),
                )

                for row in rows:
                    target = row["target_entity_id"]
                    if target in visited:
                        continue
                    visited.add(target)
                    new_entity_path = entity_path + [target]
                    new_rel_types = rel_types + [row["relation_type"]]

                    # Collect memories linked to this terminal entity
                    mem_ids = await self._entity_memories(target)
                    if mem_ids:
                        all_paths.append(GraphPath(
                            entity_ids=new_entity_path,
                            relation_types=new_rel_types,
                            hop_count=len(new_entity_path) - 1,
                            terminal_memory_ids=mem_ids,
                        ))

                    queue.append((target, new_entity_path, new_rel_types, hops + 1))

        return all_paths

    async def _entity_memories(self, entity_id: str) -> list[str]:
        """Find memories linked to an entity via metadata_json."""
        rows = await self.repository.db.fetchall(
            """
            SELECT m.id
            FROM memories m
            WHERE m.metadata_json LIKE ?
            LIMIT 10;
            """,
            (f"%{entity_id}%",),
        )
        return [row["id"] for row in rows]
