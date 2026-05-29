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
        session_id: str | None = None,
        include_global: bool = True,
        include_lessons: bool = True,
        explain_scores: bool = False,
        tag_filter: list[str] | None = None,
        tag_mode: str = "any",
        fusion_method: str = "weighted",
    ) -> list[RetrievalResult]:
        # Build visibility filter for session isolation
        visibility_sql, visibility_params = self._build_visibility_filter(
            session_id=session_id,
            scope_filter=scope_filter,
            include_global=include_global,
        )

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

            # Session isolation: filter by session_id and scope
            mem_scope = str(memory.get("scope", "global"))
            mem_session = memory.get("session_id")

            # Scope filter
            if scope_filter is not None and mem_scope != scope_filter:
                continue

            # Session isolation
            if session_id is not None:
                if mem_scope == "global":
                    pass  # always visible when include_global=True
                elif mem_session == session_id:
                    pass  # same session
                elif include_global and mem_scope == "global":
                    pass
                else:
                    continue  # different session, exclude
            elif not include_global:
                if mem_scope == "global":
                    continue

            if tag_filter and not self._match_tags(memory.get("tags_json", "[]"), tag_filter, tag_mode):
                continue
            memories.append(memory)

        weights = self._intent_weights(intent)
        results: list[RetrievalResult] = []
        now = datetime.now(timezone.utc)
        query_tokens = self._tokens(query)

        for memory in memories:
            memory_id = str(memory.get("id") or memory.get("memory_id"))
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
                    source_type=str(memory.get("source_type", "unknown")),
                    verification_status=str(memory.get("verification_status", "unverified")),
                    trust_score=float(memory.get("trust_score", 0.5)),
                )
            )

        results.sort(key=lambda item: item.final_score, reverse=True)

        # LESSON fusion: boost matching lesson memories
        if include_lessons:
            results = await self._merge_lesson_candidates(
                results,
                query=query,
                intent=str(intent.value) if intent else None,
                session_id=session_id,
                scope_filter=scope_filter,
                include_global=include_global,
                limit=limit,
            )

        return results[:limit]

    @staticmethod
    def _build_visibility_filter(
        *,
        session_id: str | None,
        scope_filter: str | None,
        include_global: bool = True,
    ) -> tuple[str, list[Any]]:
        """Build WHERE clause for session/scope visibility filtering."""
        clauses = ["active_state = 'active'"]
        params: list[Any] = []

        visible: list[str] = []

        if session_id:
            visible.append("session_id = ?")
            params.append(session_id)

        if scope_filter:
            visible.append("scope = ?")
            params.append(scope_filter)
        elif not session_id:
            # No session isolation — unfiltered
            if not scope_filter:
                return " AND ".join(clauses), params

        if include_global:
            visible.append("scope = 'global'")

        if visible:
            clauses.append("(" + " OR ".join(visible) + ")")

        return " AND ".join(clauses), params

    def _intent_weights(self, intent: RetrievalIntent | None) -> dict[str, float]:
        base = {
            "semantic": 0.25,
            "keyword": 0.25,
            "temporal": 0.15,
            "entity": 0.10,
            "importance": 0.15,
            "episodic": 0.10,
        }
        if intent is None:
            return base

        overrides = {
            RetrievalIntent.CODING: {"keyword": 0.35, "entity": 0.20, "semantic": 0.20, "temporal": 0.05},
            RetrievalIntent.DEBUGGING: {"temporal": 0.30, "keyword": 0.25, "episodic": 0.20},
            RetrievalIntent.DEPLOYMENT: {"temporal": 0.25, "episodic": 0.25},
            RetrievalIntent.TROUBLESHOOTING: {"episodic": 0.25, "keyword": 0.30},
            RetrievalIntent.PREFERENCE: {"importance": 0.25, "semantic": 0.30},
            RetrievalIntent.PROJECT: {"entity": 0.25, "importance": 0.20},
            RetrievalIntent.WORKFLOW: {"episodic": 0.30, "entity": 0.15},
        }
        result = dict(base)
        result.update(overrides.get(intent, {}))
        return result

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())

    @staticmethod
    def _keyword_overlap(query_tokens: set[str], content_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(query_tokens & content_tokens) / len(query_tokens)

    @staticmethod
    def _entity_overlap(query_tokens: set[str], entities_json: str) -> float:
        import json
        try:
            entities = json.loads(entities_json or "[]")
        except (ValueError, TypeError):
            return 0.0
        if not entities:
            return 0.0
        entity_tokens = set("".join(ch.lower() if ch.isalnum() else " " for ch in str(e)).split() for e in entities)
        hits = sum(1 for t in query_tokens if any(t in e for e in entity_tokens))
        return hits / len(query_tokens) if query_tokens else 0.0

    @staticmethod
    def _temporal_score(valid_from_or_updated: str, now: datetime) -> float:
        if not valid_from_or_updated:
            return 0.5
        try:
            dt = datetime.fromisoformat(valid_from_or_updated.replace("Z", "+00:00"))
            delta_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
            return max(0.0, 1.0 - delta_hours / 720.0)  # decay over 30 days
        except (ValueError, OverflowError):
            return 0.5

    @staticmethod
    def _match_tags(tags_json: str, filters: list[str], mode: str) -> bool:
        import json
        try:
            tags = [t.lower() for t in json.loads(tags_json or "[]")]
        except (ValueError, TypeError):
            return True
        filter_lower = [f.lower() for f in filters]
        if mode == "all":
            return all(f in tags for f in filter_lower)
        return any(f in tags for f in filter_lower)

    def _build_explanation(
        self,
        semantic_score: float,
        keyword_score: float,
        temporal_score: float,
        entity_score: float,
        importance_score: float,
        episodic_score: float,
        intent: RetrievalIntent | None = None,
    ) -> str:
        parts = [
            f"semantic={semantic_score:.2f}",
            f"keyword={keyword_score:.2f}",
            f"temporal={temporal_score:.2f}",
            f"entity={entity_score:.2f}",
            f"importance={importance_score:.2f}",
            f"episodic={episodic_score:.2f}",
        ]
        if intent:
            parts.append(f"intent={intent.value}")
        return ", ".join(parts)

    # ── LESSON retrieval boost ──

    async def _merge_lesson_candidates(
        self,
        results: list[RetrievalResult],
        *,
        query: str,
        intent: str | None,
        session_id: str | None,
        scope_filter: str | None,
        include_global: bool,
        limit: int,
    ) -> list[RetrievalResult]:
        from memoryx.cognitive.lessons import LessonPolicyEngine
        engine = LessonPolicyEngine(repository=self.repository)
        lessons = await engine.match(
            query=query,
            intent=intent,
            session_id=session_id,
            scope_filter=scope_filter,
            include_global=include_global,
            limit=max(5, limit),
        )
        if not lessons:
            return results

        by_id = {r.memory_id: r for r in results}
        for lesson in lessons:
            mid = lesson["memory_id"]
            match_score = float(lesson.get("lesson_match_score", 0.0))
            boost = 0.35 + 0.55 * match_score

            if mid in by_id:
                item = by_id[mid]
                item.final_score = item.final_score + boost
                item.explanation = item.explanation + f", lesson_boost={boost:.2f}"
                continue

            item = self._lesson_to_retrieval_result(lesson, boost=boost)
            results.append(item)

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:limit]

    @staticmethod
    def _lesson_to_retrieval_result(lesson: dict, *, boost: float) -> RetrievalResult:
        mid = lesson.get("memory_id", "")
        return RetrievalResult(
            memory_id=mid,
            content=lesson.get("lesson_text") or lesson.get("content", ""),
            memory_type="LESSON",
            scope=lesson.get("scope", "global"),
            semantic_score=0.0,
            keyword_score=float(lesson.get("lesson_match_score", 0.0)),
            temporal_score=0.0,
            entity_score=0.0,
            importance_score=float(lesson.get("severity", 0.0)),
            episodic_score=0.0,
            final_score=min(1.0, 0.60 + boost),
            explanation=f"lesson_boost={boost:.2f},"
            f"match={lesson.get('lesson_match_score',0):.2f},"
            f"policy={lesson.get('policy_type','')}",
            source_type=str(lesson.get("source_type", "user_explicit")),
            verification_status=str(lesson.get("verification_status", "verified")),
            trust_score=float(lesson.get("trust_score", 0.9)),
        )
