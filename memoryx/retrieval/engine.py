from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .models import RetrievalIntent, RetrievalResult


class HybridRetrievalEngine:
    def __init__(self, *, repository, vector_store) -> None:
        self.repository = repository
        self.vector_store = vector_store

    async def retrieve(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        intent: RetrievalIntent | None = None,
        scope_filter: str | None = None,
        tag_filter: list[str] | None = None,
        tag_mode: str = "any",
        fusion_method: str = "weighted",
    ) -> list[RetrievalResult]:
        vector_hits = await self.vector_store.search(query_vector, limit=max(limit * 3, 10))
        vector_scores = {item["memory_id"]: float(item["score"]) for item in vector_hits}

        keyword_hits = await self.repository.search_full_text(query, limit=max(limit * 3, 10))
        keyword_map = {item["memory_id"]: item for item in keyword_hits}

        candidate_ids = list(dict.fromkeys([*vector_scores.keys(), *keyword_map.keys()]))
        memories: list[dict[str, Any]] = []
        for memory_id in candidate_ids:
            memory = await self.repository.get_memory(memory_id)
            if memory is None:
                continue
            if scope_filter is not None and memory.get("scope") != scope_filter:
                continue
            if tag_filter and not self._match_tags(memory.get("tags_json", "[]"), tag_filter, tag_mode):
                continue
            memories.append(memory)

        weights = self._intent_weights(intent)
        results: list[RetrievalResult] = []
        now = datetime.now(timezone.utc)
        query_tokens = self._tokens(query)

        for memory in memories:
            memory_id = str(memory["memory_id"])
            content = str(memory["content"])
            semantic_score = vector_scores.get(memory_id, 0.0)
            keyword_score = self._keyword_overlap(query_tokens, self._tokens(content))
            importance_score = float(memory.get("importance_score", 0.0))
            entity_score = self._entity_overlap(query_tokens, memory.get("entities_json", "[]"))
            episodic_score = 0.15 if str(memory.get("memory_type", "")) == "EPISODIC" else 0.0
            temporal_score = self._temporal_score(str(memory.get("valid_from") or memory.get("updated_at") or ""), now)

            final_score = (
                semantic_score * weights["semantic"]
                + keyword_score * weights["keyword"]
                + temporal_score * weights["temporal"]
                + entity_score * weights["entity"]
                + importance_score * weights["importance"]
                + episodic_score * weights["episodic"]
            )

            explanation = self._build_explanation(
                semantic_score=semantic_score,
                keyword_score=keyword_score,
                temporal_score=temporal_score,
                entity_score=entity_score,
                importance_score=importance_score,
                episodic_score=episodic_score,
                intent=intent,
            )
            results.append(
                RetrievalResult(
                    memory_id=memory_id,
                    content=content,
                    memory_type=str(memory.get("memory_type", "")),
                    scope=str(memory.get("scope", "global")),
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    temporal_score=temporal_score,
                    entity_score=entity_score,
                    importance_score=importance_score,
                    episodic_score=episodic_score,
                    final_score=final_score,
                    explanation=explanation,
                )
            )

        results.sort(key=lambda item: item.final_score, reverse=True)
        return results[:limit]

    def _intent_weights(self, intent: RetrievalIntent | None) -> dict[str, float]:
        base = {
            "semantic": 1.0,
            "keyword": 1.0,
            "temporal": 0.45,
            "entity": 0.35,
            "importance": 0.6,
            "episodic": 0.4,
        }
        if intent == RetrievalIntent.DEBUGGING:
            base["episodic"] = 0.8
            base["keyword"] = 1.2
            base["semantic"] = 1.1
        elif intent == RetrievalIntent.DEPLOYMENT:
            base["episodic"] = 0.7
            base["temporal"] = 0.6
        elif intent == RetrievalIntent.PREFERENCE:
            base["importance"] = 0.8
            base["entity"] = 0.5
        elif intent == RetrievalIntent.PLANNING:
            base["keyword"] = 1.1
            base["importance"] = 0.75
        return base

    def _tokens(self, text: str) -> list[str]:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
        return [token for token in normalized.split() if token]

    def _keyword_overlap(self, left: list[str], right: list[str]) -> float:
        if not left or not right:
            return 0.0
        left_counts = Counter(left)
        right_counts = Counter(right)
        intersection = sum(min(left_counts[token], right_counts[token]) for token in left_counts.keys() | right_counts.keys())
        return intersection / max(len(left), len(right), 1)

    def _entity_overlap(self, query_tokens: list[str], entities_json: str) -> float:
        joined = entities_json.lower()
        if not joined or joined == "[]":
            return 0.0
        matches = sum(1 for token in query_tokens if token in joined)
        return min(1.0, matches / max(len(query_tokens), 1))

    def _temporal_score(self, timestamp_text: str, now: datetime) -> float:
        if not timestamp_text:
            return 0.0
        try:
            timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        age_seconds = max((now - timestamp).total_seconds(), 0.0)
        days = age_seconds / 86400.0
        return max(0.0, 1.0 - min(days / 365.0, 1.0))

    def _build_explanation(
        self,
        *,
        semantic_score: float,
        keyword_score: float,
        temporal_score: float,
        entity_score: float,
        importance_score: float,
        episodic_score: float,
        intent: RetrievalIntent | None,
    ) -> str:
        parts = [
            f"semantic={semantic_score:.2f}",
            f"keyword={keyword_score:.2f}",
            f"importance={importance_score:.2f}",
        ]
        if temporal_score > 0:
            parts.append(f"temporal={temporal_score:.2f}")
        if entity_score > 0:
            parts.append(f"entity={entity_score:.2f}")
        if episodic_score > 0:
            parts.append(f"episodic={episodic_score:.2f}")
        if intent is not None:
            parts.append(f"intent={intent.value}")
        return " | ".join(parts) if parts else ""

    def _match_tags(self, tags_json: str, required: list[str], mode: str = "any") -> bool:
        import json
        try:
            tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(tags, list):
            return False
        tag_set = {str(t).strip().lower() for t in tags}
        required_set = {str(t).strip().lower() for t in required}
        if mode == "all":
            return required_set.issubset(tag_set)
        return bool(required_set & tag_set)

    async def trace_retrieval(
        self,
        *,
        query: str,
        query_vector: list[float],
        memory_id: str,
    ) -> dict:
        """解释性追踪：展示为什么这条记忆被召回。"""
        result = None
        all_results = await self.retrieve(query=query, query_vector=query_vector, limit=20)
        for r in all_results:
            if r.memory_id == memory_id:
                result = r
                break
        if not result:
            return {"memory_id": memory_id, "found": False}

        return {
            "memory_id": memory_id,
            "content": result.content,
            "memory_type": result.memory_type,
            "found": True,
            "scores": {
                "semantic": result.semantic_score,
                "keyword": result.keyword_score,
                "temporal": result.temporal_score,
                "entity": result.entity_score,
                "importance": result.importance_score,
                "episodic": result.episodic_score,
            },
            "final_score": result.final_score,
            "explanation": result.explanation,
        }
