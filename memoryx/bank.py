from __future__ import annotations

import re
from typing import Any

from .storage import MemoryRecord


class MemoryBank:
    """
    动态记忆银行 — 隔离的记忆命名空间。

    类似 Hindsight 的 memory banks，每个银行有独立的记忆集、提取指令和模板化名称。
    支持模板占位符：{profile}, {user}, {session}, {project}, {platform}
    """

    def __init__(self, *, bank_id: str, repository, extraction_instruction: str = "") -> None:
        self.bank_id = bank_id
        self.repository = repository
        self.extraction_instruction = extraction_instruction

    @staticmethod
    def resolve_template(template: str, **context: str) -> str:
        """解析模板占位符。"""
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return context.get(key, match.group(0))
        return re.sub(r"\{(\w+)\}", _replace, template)

    async def store(self, memory_type: str, content: str, **kwargs: Any) -> str:
        """存入一条带 bank 标记的记忆。"""
        record = MemoryRecord(
            memory_id=kwargs.pop("memory_id", __import__("uuid").uuid4().hex),
            memory_type=memory_type,
            content=content,
            scope=self.bank_id,
            **kwargs,
        )
        return await self.repository.store_memory(record)

    async def search(self, query: str, query_vector: list[float], *, vector_store=None, limit: int = 10) -> list[dict]:
        """在当前银行范围内搜索。"""
        from .retrieval import HybridRetrievalEngine
        engine = HybridRetrievalEngine(repository=self.repository, vector_store=vector_store)
        results = await engine.retrieve(query=query, query_vector=query_vector, limit=limit, scope_filter=self.bank_id)
        return [{"memory_id": r.memory_id, "content": r.content, "memory_type": r.memory_type, "final_score": r.final_score} for r in results]

    async def count(self) -> int:
        """统计当前银行内活跃的记忆数。"""
        memories = await self.repository.list_active_memories(limit=10000)
        return sum(1 for m in memories if m.get("scope") == self.bank_id)

    async def clear(self) -> int:
        """清除当前银行的所有记忆（软删除）。"""
        memories = await self.repository.list_memories(limit=10000)
        count = 0
        for m in memories:
            if m.get("scope") == self.bank_id:
                await self.repository.rollback_memory(m["memory_id"])
                count += 1
        return count
