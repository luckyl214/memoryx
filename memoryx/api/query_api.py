from __future__ import annotations

import json
from uuid import uuid4

from memoryx.recall import ActiveRecallEngine
from memoryx.reflect import ReflectEngine
from memoryx.reflection import ReflectionEngine
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.conversation_log import ConversationLogStore
from memoryx.storage import MemoryRecord
from memoryx.temporal import TemporalMemoryEngine


class MemoryQueryAPI:
    def __init__(self, *, repository, vector_store) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.recall_engine = ActiveRecallEngine(repository=repository, vector_store=vector_store)
        self.reflection_engine = ReflectionEngine(repository=repository)
        self.temporal_engine = TemporalMemoryEngine(repository=repository)
        self.retrieval_engine = HybridRetrievalEngine(repository=repository, vector_store=vector_store)
        self.reflect_engine = ReflectEngine(retrieval_engine=self.retrieval_engine)
        self.conversation_log = ConversationLogStore(repository=repository)

    async def search(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        tag_filter: list[str] | None = None,
        tag_mode: str = "any",
    ) -> list[dict]:
        results = await self.retrieval_engine.retrieve(
            query=query, query_vector=query_vector, limit=limit,
            tag_filter=tag_filter, tag_mode=tag_mode,
        )
        return [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "memory_type": item.memory_type,
                "scope": item.scope,
                "final_score": item.final_score,
                "explanation": item.explanation,
            }
            for item in results
        ]

    async def conversation_search(
        self,
        *,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """搜索 L0 原始对话历史（FTS5）。"""
        return await self.conversation_log.search(query, session_id=session_id, limit=limit)

    async def recall(self, *, query: str, query_vector: list[float], limit: int = 5) -> dict:
        return await self.recall_engine.recall(query=query, query_vector=query_vector, limit=limit)

    async def store(self, *, memory_type: str, content: str, scope: str = "global", importance_score: float = 0.5, confidence_score: float = 0.5) -> str:
        record = MemoryRecord(
            memory_id=uuid4().hex,
            memory_type=memory_type,
            content=content,
            scope=scope,
            importance_score=importance_score,
            confidence_score=confidence_score,
        )
        return await self.repository.store_memory(record)

    async def reflect(self) -> dict:
        return await self.reflection_engine.generate_reflection()

    async def reflect_synthesis(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> dict:
        """跨记忆 LLM 合成推理。"""
        return await self.reflect_engine.reflect(query=query, query_vector=query_vector, limit=limit)

    async def tag(self, memory_id: str, tag: str) -> None:
        """为一条记忆添加标签。"""
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return
        tags = json.loads(memory.get("tags_json", "[]") or "[]")
        tag_clean = tag.strip().lower()
        if tag_clean not in tags:
            tags.append(tag_clean)
            await self.repository.db.execute(
                "UPDATE memories SET tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (json.dumps(tags, ensure_ascii=False), memory_id),
            )

    async def untag(self, memory_id: str, tag: str) -> None:
        """从一条记忆移除标签。"""
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return
        tags = json.loads(memory.get("tags_json", "[]") or "[]")
        tag_clean = tag.strip().lower()
        if tag_clean in tags:
            tags.remove(tag_clean)
            await self.repository.db.execute(
                "UPDATE memories SET tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (json.dumps(tags, ensure_ascii=False), memory_id),
            )

    async def list_tags(self, memory_id: str) -> list[str]:
        """查看一条记忆的所有标签。"""
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return []
        return json.loads(memory.get("tags_json", "[]") or "[]")

    async def feedback(self, memory_id: str, positive: bool) -> dict:
        """
        用户反馈训练 — 调整记忆的置信度和强化分数。

        positive=True: 增加 confidence_score 和 reinforcement_score
        positive=False: 降低 confidence_score，标记为需要审核
        """
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return {"memory_id": memory_id, "applied": False, "error": "not found"}

        current_confidence = float(memory.get("confidence_score", 0.5))
        current_reinforcement = float(memory.get("reinforcement_score", 0.0))

        if positive:
            new_confidence = min(1.0, current_confidence + 0.15)
            new_reinforcement = min(1.0, current_reinforcement + 0.2)
        else:
            new_confidence = max(0.0, current_confidence - 0.3)
            new_reinforcement = max(0.0, current_reinforcement - 0.1)

        await self.repository.db.execute(
            "UPDATE memories SET confidence_score = ?, reinforcement_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (new_confidence, new_reinforcement, memory_id),
        )
        await self.repository.append_audit(
            "user_feedback",
            memory_id,
            {"positive": positive, "old_confidence": current_confidence, "new_confidence": new_confidence},
        )
        return {"memory_id": memory_id, "applied": True, "new_confidence": new_confidence, "new_reinforcement": new_reinforcement}

    async def timeline(self, *, memory_id: str) -> dict:
        versions = await self.temporal_engine.timeline(memory_id=memory_id)
        return {
            "memory_id": memory_id,
            "versions": [
                {
                    "memory_id": state.memory_id,
                    "content": state.content,
                    "version_number": state.version_number,
                    "valid_from": state.valid_from,
                    "valid_to": state.valid_to,
                    "active_state": state.active_state,
                    "superseded_by": state.superseded_by,
                }
                for state in versions
            ],
        }

    async def project_context(self, *, query: str, query_vector: list[float], limit: int = 5) -> dict:
        return await self.recall_engine.project_recall(query=query, query_vector=query_vector, limit=limit)
