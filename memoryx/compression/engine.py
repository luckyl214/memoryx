from __future__ import annotations

from collections import defaultdict


class SemanticCompressionEngine:
    """语义压缩引擎 — 聚类、去重、层级摘要。

    P0-D: 保留所有旧方法，对齐新 schema (id/memory_id, active_state TEXT,
    archived_memories 新结构)。新增 run_llm_consolidation() 入口。
    """

    def __init__(self, *, repository) -> None:
        self.repository = repository

    # ── 保留：旧方法（兼容）─────────────────────────────────────────

    async def cluster_memories(self) -> list[dict]:
        """按内容前缀聚类活跃记忆，返回 {memory_ids, memories}。"""
        memories = await self.repository.list_active_memories(limit=1000)
        groups: dict[str, list[dict]] = defaultdict(list)
        for memory in memories:
            key = self._cluster_key(str(memory.get("content", "")))
            groups[key].append(memory)

        clusters: list[dict] = []
        for group in groups.values():
            if len(group) < 2:
                continue
            clusters.append(
                {
                    "memory_ids": [item["id"] for item in group],
                    "memories": group,
                }
            )
        return clusters

    def summarize_cluster(self, memories: list[dict]) -> str:
        """摘取最长公共前缀作为簇摘要。"""
        if not memories:
            return ""
        contents = [
            str(item.get("content", "")).strip()
            for item in memories
            if str(item.get("content", "")).strip()
        ]
        if not contents:
            return ""
        prefix = self._longest_common_prefix(contents)
        if prefix:
            return prefix
        return contents[0]

    async def merge_duplicate_chunks(self) -> int:
        """合并完全相同的 memory，将副本 supersede 到主副本。"""
        memories = await self.repository.list_active_memories(limit=1000)
        by_content: dict[str, list[dict]] = defaultdict(list)
        for memory in memories:
            by_content[str(memory.get("content", "")).strip().lower()].append(memory)

        merged = 0
        for group in by_content.values():
            if len(group) < 2:
                continue
            ordered = sorted(
                group,
                key=lambda item: float(item.get("importance_score", 0.0)),
                reverse=True,
            )
            primary = ordered[0]
            for duplicate in ordered[1:]:
                await self.repository.supersede_memory(duplicate["id"], primary["id"])
                merged += 1
        return merged

    async def compress_to_hierarchical_summary(self, *, session_id: str) -> dict[str, int]:
        """全量压缩：聚类 → 摘要 → 归档高衰减记忆。"""
        clusters = await self.cluster_memories()
        summaries: list[str] = []
        archived = 0

        for cluster in clusters:
            summary = self.summarize_cluster(cluster["memories"])
            if summary:
                summaries.append(summary)

        memories = await self.repository.list_memories(limit=1000)
        for memory in memories:
            decay = float(memory.get("decay_score", 0.0))
            access = int(memory.get("access_count", 0))
            active = memory.get("active_state", "active")
            if decay >= 0.9 and access == 0 and active == "active":
                from uuid import uuid4
                await self.repository.db.execute(
                    """
                    INSERT INTO archived_memories (
                        id, memory_id, archived_reason, archived_at, checksum, metadata_json
                    ) VALUES (?, ?, ?, datetime('now'), ?, ?);
                    """,
                    (
                        uuid4().hex,
                        memory["id"],
                        "semantic_compression",
                        self.repository.checksum(f"archive:{memory['id']}"),
                        "{}",
                    ),
                )
                await self.repository.rollback_memory(memory["id"])
                archived += 1

        hierarchical_summary = (
            " || ".join(summaries) if summaries else "No compressible clusters found."
        )
        await self.repository.add_session_summary(
            session_id=session_id,
            summary=hierarchical_summary,
            source_count=len(summaries),
        )
        return {"clusters": len(clusters), "archived": archived}

    # ── 新增：LLM consolidation 入口 ──────────────────────────────

    async def run_llm_consolidation(
        self,
        *,
        limit: int = 100,
        dry_run: bool = True,
        cluster_key: str | None = None,
    ) -> dict:
        """P0-D: LLM 驱动的记忆整合入口。

        渐进式替代旧压缩管线。默认 dry_run=True。
        """
        from memoryx.llm_consolidation_engine import LLMConsolidationEngine
        engine = LLMConsolidationEngine(repository=self.repository)
        return await engine.run(
            limit=limit,
            dry_run=dry_run,
            cluster_key=cluster_key,
        )

    # ── 内部辅助 ──────────────────────────────────────────────────

    def _cluster_key(self, content: str) -> str:
        words = [word for word in content.lower().split() if word]
        return " ".join(words[:4])

    def _longest_common_prefix(self, contents: list[str]) -> str:
        first = min(contents, key=len)
        last = max(contents)
        index = 0
        while (
            index < len(first) and index < len(last) and first[index] == last[index]
        ):
            index += 1
        return first[:index].strip(" ,;:-")
