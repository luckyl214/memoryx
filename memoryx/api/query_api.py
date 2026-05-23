from __future__ import annotations

import inspect
import json
from uuid import uuid4

from memoryx.recall import ActiveRecallEngine
from memoryx.reflect import ReflectEngine
from memoryx.reflection import ReflectionEngine
from memoryx.retrieval import HybridRetrievalEngine
from memoryx.conversation_log import ConversationLogStore
from memoryx.storage import MemoryRecord
from memoryx.temporal import TemporalMemoryEngine

try:
    from memoryx.cognitive.feedback import FeedbackLearningEngine
    from memoryx.cognitive.models import FeedbackEvent
except Exception:
    FeedbackLearningEngine = None  # type: ignore[assignment]
    FeedbackEvent = None  # type: ignore[assignment]


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
        self.feedback_learning_engine = (
            FeedbackLearningEngine(repository=repository) if FeedbackLearningEngine is not None else None
        )

    async def search(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        tag_filter: list[str] | None = None,
        tag_mode: str = "any",
        session_id: str | None = None,
        scope_filter: str | None = None,
        include_global: bool = True,
        include_lessons: bool = True,
        explain_scores: bool = False,
    ) -> list[dict]:
        kwargs = {
            "query": query,
            "query_vector": query_vector,
            "limit": limit,
            "tag_filter": tag_filter,
            "tag_mode": tag_mode,
        }
        sig = inspect.signature(self.retrieval_engine.retrieve)
        for key, value in {
            "session_id": session_id,
            "scope_filter": scope_filter,
            "include_global": include_global,
            "include_lessons": include_lessons,
            "explain_scores": explain_scores,
        }.items():
            if key in sig.parameters:
                kwargs[key] = value

        results = await self.retrieval_engine.retrieve(**kwargs)
        return [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "memory_type": item.memory_type,
                "scope": getattr(item, "scope", "global"),
                "final_score": item.final_score,
                "explanation": getattr(item, "explanation", ""),
                "explain_scores": getattr(item, "explain_scores", None),
            }
            for item in results
        ]

    async def conversation_search(self, *, query: str, session_id: str | None = None, limit: int = 10) -> list[dict]:
        return await self.conversation_log.search(query, session_id=session_id, limit=limit)

    async def recall(self, *, query: str, query_vector: list[float], limit: int = 5) -> dict:
        return await self.recall_engine.recall(query=query, query_vector=query_vector, limit=limit)

    async def store(
        self,
        *,
        memory_type: str,
        content: str,
        scope: str = "global",
        importance_score: float = 0.5,
        confidence_score: float = 0.5,
        session_id: str | None = None,
    ) -> str:
        record = MemoryRecord(
            memory_id=uuid4().hex,
            memory_type=memory_type,
            content=content,
            scope=scope,
            session_id=session_id,
            importance_score=importance_score,
            confidence_score=confidence_score,
        )
        return await self.repository.store_memory(record)

    async def reflect(self) -> dict:
        return await self.reflection_engine.generate_reflection()

    async def reflect_synthesis(self, *, query: str, query_vector: list[float], limit: int = 10) -> dict:
        return await self.reflect_engine.reflect(query=query, query_vector=query_vector, limit=limit)

    async def tag(self, memory_id: str, tag: str) -> None:
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return
        tags = json.loads(memory.get("tags_json", "[]") or "[]")
        tag_clean = tag.strip().lower()
        if tag_clean not in tags:
            tags.append(tag_clean)
            await self.repository.update_memory_versioned(
                memory_id,
                {"tags_json": json.dumps(tags, ensure_ascii=False)},
                actor="query_api",
                reason="tag memory",
            )

    async def untag(self, memory_id: str, tag: str) -> None:
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return
        tags = json.loads(memory.get("tags_json", "[]") or "[]")
        tag_clean = tag.strip().lower()
        if tag_clean in tags:
            tags.remove(tag_clean)
            await self.repository.update_memory_versioned(
                memory_id,
                {"tags_json": json.dumps(tags, ensure_ascii=False)},
                actor="query_api",
                reason="untag memory",
            )

    async def list_tags(self, memory_id: str) -> list[str]:
        memory = await self.repository.get_memory(memory_id)
        if not memory:
            return []
        return json.loads(memory.get("tags_json", "[]") or "[]")

    async def feedback(
        self,
        memory_id: str,
        positive: bool,
        reason: str = "",
        session_id: str | None = None,
        dry_run: bool = False,
        propagate: bool = True,
    ) -> dict:
        if self.feedback_learning_engine is not None and FeedbackEvent is not None:
            result = await self.feedback_learning_engine.apply_feedback(
                FeedbackEvent(memory_id=memory_id, positive=positive, session_id=session_id, reason=reason, source="rest_api"),
                propagate=propagate,
                dry_run=dry_run,
                auto_lesson=True,
            )
            return {
                "memory_id": memory_id,
                "applied": not dry_run,
                "dry_run": dry_run,
                "affected": [
                    {
                        "memory_id": c.memory_id,
                        "score": c.score,
                        "confidence_delta": c.confidence_delta,
                        "applied": c.applied,
                    }
                    for c in result.affected
                ],
                "lesson_created": result.lesson_created,
            }

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

        if not dry_run:
            await self.repository.update_memory_versioned(
                memory_id,
                {"confidence_score": new_confidence, "reinforcement_score": new_reinforcement},
                actor="feedback",
                reason=reason or "user feedback",
            )
        return {
            "memory_id": memory_id,
            "applied": not dry_run,
            "dry_run": dry_run,
            "new_confidence": new_confidence,
            "new_reinforcement": new_reinforcement,
        }

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
