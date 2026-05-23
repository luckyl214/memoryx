from __future__ import annotations

import json
import math
import re
from typing import Any
from uuid import uuid4

from .lesson import LessonAbstractionEngine
from .models import FeedbackEvent, PropagationCandidate, PropagationResult

_WORD_RE = re.compile(r"[\w\-\.]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "") if len(t.strip()) > 1}


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MemorySimilarityEngine:
    """Dependency-light similarity engine for feedback propagation."""

    def __init__(self, *, repository, vector_store=None) -> None:
        self.repository = repository
        self.vector_store = vector_store

    async def candidates(
        self,
        memory_id: str,
        *,
        top_k: int = 50,
        include_graph_neighbors: bool = True,
    ) -> list[PropagationCandidate]:
        root = await self.repository.get_memory(memory_id)
        if not root:
            return []
        root_tokens = _tokens(str(root.get("content") or ""))
        root_entities = self._entities(root)
        candidates: dict[str, PropagationCandidate] = {}

        rows = await self.repository.list_active_memories(limit=1000)
        for memory in rows:
            mid = str(memory.get("id") or memory.get("memory_id") or "")
            if not mid or mid == memory_id:
                continue
            kw = self._jaccard(root_tokens, _tokens(str(memory.get("content") or "")))
            ent = self._jaccard(root_entities, self._entities(memory))
            graph_bonus = 0.08 if include_graph_neighbors and ent > 0 else 0.0
            score = 0.55 * kw + 0.35 * ent + graph_bonus
            if score > 0:
                candidates[mid] = PropagationCandidate(
                    memory_id=mid,
                    score=score,
                    keyword_similarity=kw,
                    entity_overlap=ent,
                    graph_distance=1 if ent > 0 else None,
                    reason="keyword/entity similarity",
                )

        # Optional cached edges. This lets a vector/graph maintenance job precompute better pairs.
        try:
            edge_rows = await self.repository.db.fetchall(
                """
                SELECT target_memory_id, combined_score, keyword_similarity, semantic_similarity, entity_overlap, graph_distance
                FROM memory_similarity_edges
                WHERE source_memory_id = ?
                ORDER BY combined_score DESC LIMIT ?;
                """,
                (memory_id, top_k),
            )
        except Exception:
            edge_rows = []
        for row in edge_rows:
            item = dict(row)
            mid = str(item["target_memory_id"])
            cached = PropagationCandidate(
                memory_id=mid,
                score=float(item.get("combined_score") or 0.0),
                keyword_similarity=float(item.get("keyword_similarity") or 0.0),
                semantic_similarity=float(item.get("semantic_similarity") or 0.0),
                entity_overlap=float(item.get("entity_overlap") or 0.0),
                graph_distance=item.get("graph_distance"),
                reason="cached similarity edge",
            )
            if mid not in candidates or cached.score > candidates[mid].score:
                candidates[mid] = cached

        result = list(candidates.values())
        result.sort(key=lambda c: c.score, reverse=True)
        return result[:top_k]

    async def score_pair(self, a: dict[str, Any], b: dict[str, Any]) -> float:
        kw = self._jaccard(_tokens(str(a.get("content") or "")), _tokens(str(b.get("content") or "")))
        ent = self._jaccard(self._entities(a), self._entities(b))
        return 0.65 * kw + 0.35 * ent

    def _entities(self, memory: dict[str, Any]) -> set[str]:
        meta = _loads(memory.get("metadata_json"), {})
        values: list[Any] = []
        if isinstance(meta, dict):
            values.extend(meta.get("entities") or [])
            values.extend(meta.get("tags") or [])
        return {str(v).strip().lower() for v in values if str(v).strip()}

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)


class FeedbackLearningEngine:
    """Closed loop: feedback -> similarity propagation -> LESSON creation."""

    def __init__(
        self,
        *,
        repository,
        similarity_engine: MemorySimilarityEngine | None = None,
        lesson_engine: LessonAbstractionEngine | None = None,
    ) -> None:
        self.repository = repository
        self.similarity_engine = similarity_engine or MemorySimilarityEngine(repository=repository)
        self.lesson_engine = lesson_engine or LessonAbstractionEngine(repository=repository)

    async def apply_feedback(
        self,
        event: FeedbackEvent,
        *,
        propagate: bool = True,
        dry_run: bool = False,
        auto_lesson: bool = True,
        auto_apply_threshold: float = 0.82,
        preview_threshold: float = 0.65,
    ) -> PropagationResult:
        memory = await self.repository.get_memory(event.memory_id)
        if not memory:
            return PropagationResult(root_memory_id=event.memory_id, dry_run=dry_run)

        old_confidence = float(memory.get("confidence_score") or 0.5)
        old_reinforcement = float(memory.get("reinforcement_score") or 0.0)
        root_delta = 0.15 if event.positive else -0.30
        new_confidence = _clamp(old_confidence + root_delta)
        new_reinforcement = _clamp(old_reinforcement + (0.20 if event.positive else -0.10))
        feedback_id = uuid4().hex

        if not dry_run:
            await self.repository.db.execute(
                """
                INSERT INTO memory_feedback_events(
                    id, memory_id, session_id, positive, reason, source,
                    old_confidence, new_confidence, old_reinforcement, new_reinforcement,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    feedback_id,
                    event.memory_id,
                    event.session_id,
                    1 if event.positive else 0,
                    event.reason,
                    event.source,
                    old_confidence,
                    new_confidence,
                    old_reinforcement,
                    new_reinforcement,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            await self._versioned_update(
                event.memory_id,
                {"confidence_score": new_confidence, "reinforcement_score": new_reinforcement},
                actor="feedback",
                reason=event.reason or "user feedback",
            )
        else:
            feedback_id = f"DRY_RUN:{feedback_id}"

        result = PropagationResult(
            root_memory_id=event.memory_id,
            feedback_event_id=feedback_id,
            root_delta=root_delta,
            dry_run=dry_run,
        )

        if propagate:
            candidates = await self.similarity_engine.candidates(event.memory_id, top_k=50)
            for candidate in candidates:
                if candidate.score < preview_threshold:
                    continue
                distance_factor = math.exp(-float(candidate.graph_distance or 1) / 2.0)
                delta = root_delta * candidate.score * distance_factor
                candidate.confidence_delta = delta
                candidate.applied = (candidate.score >= auto_apply_threshold) and not dry_run
                result.affected.append(candidate)
                if not dry_run:
                    await self.repository.db.execute(
                        """
                        INSERT INTO feedback_propagations(
                            id, feedback_event_id, from_memory_id, to_memory_id,
                            propagation_score, confidence_delta, applied, reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            uuid4().hex,
                            feedback_id,
                            event.memory_id,
                            candidate.memory_id,
                            candidate.score,
                            delta,
                            1 if candidate.applied else 0,
                            candidate.reason,
                        ),
                    )
                    if candidate.applied:
                        target = await self.repository.get_memory(candidate.memory_id)
                        if target:
                            target_conf = float(target.get("confidence_score") or 0.5)
                            await self._versioned_update(
                                candidate.memory_id,
                                {"confidence_score": _clamp(target_conf + delta)},
                                actor="feedback_propagation",
                                reason=f"similar to {event.memory_id}",
                            )

        if auto_lesson and not event.positive:
            create, min_evidence = await self._lesson_creation_policy(event.memory_id, result)
            if create:
                # Include every propagated/previewed related memory as evidence.
                # The root memory is always added by LessonAbstractionEngine, so one
                # related memory is enough to form a two-item evidence set.
                evidence = [
                    c.memory_id
                    for c in result.affected
                    if c.score >= preview_threshold
                ]
                result.lesson_created = await self.lesson_engine.maybe_create_lesson(
                    root_memory_id=event.memory_id,
                    evidence_memory_ids=evidence,
                    trigger_context={
                        "reason": event.reason,
                        "session_id": event.session_id,
                        "feedback_event_id": feedback_id,
                    },
                    dry_run=dry_run,
                    min_evidence=min_evidence,
                )
        return result

    async def _lesson_creation_policy(self, memory_id: str, result: PropagationResult) -> tuple[bool, int]:
        """Decide whether negative feedback should become a LESSON.

        Policy rationale:
        - A repeated negative feedback on the same memory is enough, even without
          extra similar memories. In that case the root memory is the evidence.
        - A first negative feedback plus at least one similar affected memory is
          also enough. The evidence set is root + similar memory, which captures
          an error pattern rather than a single isolated correction.
        - Strong auto-applied propagation is treated as especially strong evidence.
        """
        row = await self.repository.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM memory_feedback_events WHERE memory_id = ? AND positive = 0;",
            (memory_id,),
        )
        negative_count = int(row["cnt"] if row else 0)
        similar_count = sum(1 for c in result.affected if c.score >= 0.65)
        applied_count = sum(1 for c in result.affected if c.applied)

        if negative_count >= 2:
            return True, 1
        if applied_count >= 1:
            return True, 2
        if similar_count >= 1:
            return True, 2
        return False, 2

    # Backward-compatible alias for tests or downstream code that reached into
    # the old private method.
    async def _should_create_lesson(self, memory_id: str, result: PropagationResult) -> bool:
        create, _ = await self._lesson_creation_policy(memory_id, result)
        return create

    async def _versioned_update(self, memory_id: str, changes: dict[str, Any], *, actor: str, reason: str) -> None:
        if hasattr(self.repository, "update_memory_versioned"):
            await self.repository.update_memory_versioned(memory_id, changes, actor=actor, reason=reason)
            return
        allowed = {"confidence_score", "reinforcement_score", "importance_score", "metadata_json", "active_state"}
        filtered = {k: v for k, v in changes.items() if k in allowed}
        if not filtered:
            return
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        await self.repository.db.execute(
            f"UPDATE memories SET {assignments}, updated_at = datetime('now') WHERE id = ?;",
            (*filtered.values(), memory_id),
        )
