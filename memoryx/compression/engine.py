from __future__ import annotations

from collections import defaultdict


class SemanticCompressionEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def cluster_memories(self) -> list[dict]:
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
                    "memory_ids": [item["memory_id"] for item in group],
                    "memories": group,
                }
            )
        return clusters

    def summarize_cluster(self, memories: list[dict]) -> str:
        if not memories:
            return ""
        contents = [str(item.get("content", "")).strip() for item in memories if str(item.get("content", "")).strip()]
        if not contents:
            return ""
        prefix = self._longest_common_prefix(contents)
        if prefix:
            return prefix
        return contents[0]

    async def merge_duplicate_chunks(self) -> int:
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

    async def compress_to_hierarchical_summary(self, *, session_id: str) -> dict[str, int]:
        clusters = await self.cluster_memories()
        summaries: list[str] = []
        archived = 0

        for cluster in clusters:
            summary = self.summarize_cluster(cluster["memories"])
            if summary:
                summaries.append(summary)

        memories = await self.repository.list_memories(limit=1000)
        for memory in memories:
            if float(memory.get("decay_score", 0.0)) >= 0.9 and int(memory.get("access_count", 0)) == 0 and int(memory.get("active_state", 1)) == 1:
                await self.repository.db.execute(
                    "INSERT INTO archived_memories(archive_id, memory_id, content, archived_at, reason) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?);",
                    (f"compression-{memory['memory_id']}", memory["memory_id"], memory["content"], "semantic_compression"),
                )
                await self.repository.rollback_memory(memory["memory_id"])
                archived += 1

        hierarchical_summary = " || ".join(summaries) if summaries else "No compressible clusters found."
        await self.repository.add_session_summary(session_id=session_id, summary=hierarchical_summary, source_count=len(summaries))
        return {"clusters": len(clusters), "archived": archived}

    def _cluster_key(self, content: str) -> str:
        words = [word for word in content.lower().split() if word]
        return " ".join(words[:4])

    def _longest_common_prefix(self, contents: list[str]) -> str:
        first = min(contents, key=len)
        last = max(contents)
        index = 0
        while index < len(first) and index < len(last) and first[index] == last[index]:
            index += 1
        return first[:index].strip(" ,;:-")
