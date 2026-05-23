from __future__ import annotations

from typing import Any, Callable


class ReflectEngine:
    """
    跨记忆 LLM 合成引擎 — 参考 Hindsight 的 hindsight_reflect 设计。

    不是简单地搜索 & 返回原始记忆，而是：
    1. 检索相关记忆
    2. 构建合成 prompt
    3. 调用 LLM 跨记忆推理合成答案
    4. 返回综合回答
    """

    def __init__(
        self,
        *,
        retrieval_engine,
        llm_synthesize: Callable[[str, list[dict[str, Any]]], str] | None = None,
    ) -> None:
        self.retrieval_engine = retrieval_engine
        self._llm_synthesize = llm_synthesize

    async def reflect(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        session_id: str | None = None,
        tag_filter: list[str] | None = None,
        tag_mode: str = "any",
    ) -> dict[str, Any]:
        """跨记忆合成推理。返回综合答案 + 原始证据。"""
        results = await self.retrieval_engine.retrieve(
            query=query,
            query_vector=query_vector,
            limit=limit,
            tag_filter=tag_filter,
            tag_mode=tag_mode,
        )

        memories = [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "memory_type": item.memory_type,
                "scope": item.scope,
                "final_score": item.final_score,
            }
            for item in results
        ]

        synthesis = ""
        if self._llm_synthesize and memories:
            synthesis = self._llm_synthesize(query, memories)

        return {
            "query": query,
            "synthesis": synthesis,
            "memories": memories,
            "count": len(memories),
        }

    @staticmethod
    def build_synthesis_prompt(query: str, memories: list[dict[str, Any]]) -> str:
        """构建合成 prompt。"""
        entries = "\n".join(
            f"[{i+1}] ({item['memory_type']}, scope={item['scope']}, score={item['final_score']:.2f}) {item['content']}"
            for i, item in enumerate(memories[:10])
        )
        return (
            f"You are a cognitive memory synthesis engine.\n"
            f"Based on the following retrieved memories, synthesize a coherent answer to the user's query.\n"
            f"If the memories contradict each other, note the contradiction.\n"
            f"If there are multiple relevant perspectives, combine them.\n"
            f"Be concise but complete.\n\n"
            f"User query: {query}\n\n"
            f"Retrieved memories:\n{entries}\n\n"
            f"Synthesis:"
        )
