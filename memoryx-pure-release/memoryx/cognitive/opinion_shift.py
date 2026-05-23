from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from statistics import mean
from typing import Any
from uuid import uuid4

from memoryx.storage import MemoryRecord

from .models import OpinionObservation, OpinionShift

_POSITIVE = {"like", "love", "prefer", "good", "great", "useful", "positive", "喜欢", "热衷", "赞成", "好", "有用", "优秀", "正面"}
_NEGATIVE = {"dislike", "hate", "bad", "poor", "doubt", "skeptical", "negative", "不喜欢", "讨厌", "怀疑", "差", "负面", "反对"}
_NEUTRAL = {"neutral", "mixed", "中性", "一般", "复杂", "保留"}
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: str | datetime | None = None) -> str:
    return _dt(value).isoformat()


class OpinionObservationExtractor:
    """Heuristic extractor; replace with an LLM extractor later if needed."""

    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client

    async def extract(self, *, memory: dict[str, Any], entity_id: str) -> OpinionObservation | None:
        memory_type = str(memory.get("memory_type") or "")
        if memory_type not in {"OPINION", "PREFERENCE", "PROJECT", "EPISODIC", "FACT"}:
            return None
        content = str(memory.get("content") or "")
        if not content.strip():
            return None
        stance = self._stance(content)
        if stance is None and memory_type not in {"OPINION", "PREFERENCE"}:
            return None
        stance_score = 0.0 if stance is None else stance
        return OpinionObservation(
            memory_id=str(memory.get("id") or memory.get("memory_id")),
            entity_id=entity_id,
            observed_at=_dt(memory.get("valid_from") or memory.get("created_at") or memory.get("updated_at")),
            stance_score=stance_score,
            sentiment_score=abs(stance_score),
            aspect=self._aspect(content),
            summary=content[:240],
            evidence_text=content[:500],
            confidence_score=0.75 if stance is not None else 0.45,
        )

    def _stance(self, text: str) -> float | None:
        lowered = text.lower()
        pos = sum(1 for w in _POSITIVE if w in lowered)
        neg = sum(1 for w in _NEGATIVE if w in lowered)
        neu = sum(1 for w in _NEUTRAL if w in lowered)
        if pos == neg == 0 and neu == 0:
            return None
        raw = (pos - neg) / max(pos + neg + neu, 1)
        return max(-1.0, min(1.0, raw))

    def _aspect(self, text: str) -> str | None:
        lowered = text.lower()
        for name, keys in {
            "plot": {"剧情", "plot", "story"},
            "character": {"人物", "角色", "character"},
            "architecture": {"架构", "architecture", "design"},
            "performance": {"性能", "performance", "latency"},
            "safety": {"安全", "risk", "危险", "safety"},
        }.items():
            if any(k in lowered for k in keys):
                return name
        return None


class OpinionShiftEngine:
    def __init__(self, *, repository, extractor: OpinionObservationExtractor | None = None) -> None:
        self.repository = repository
        self.extractor = extractor or OpinionObservationExtractor()

    async def scan_entity(
        self,
        *,
        entity_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        dry_run: bool = True,
        threshold: float = 0.35,
    ) -> list[OpinionShift]:
        observations = await self._load_or_extract(entity_id=entity_id, start=start, end=end, dry_run=dry_run)
        observations.sort(key=lambda o: o.observed_at)
        shifts: list[OpinionShift] = []
        if len(observations) < 2:
            return shifts
        for prev, cur in zip(observations, observations[1:]):
            if prev.aspect and cur.aspect and prev.aspect != cur.aspect:
                # avoid false shift across different aspects unless the stance flip is strong
                aspect_penalty = 0.10
            else:
                aspect_penalty = 0.0
            delta = cur.stance_score - prev.stance_score
            if abs(delta) < threshold + aspect_penalty:
                continue
            shift = OpinionShift(
                entity_id=entity_id,
                from_time=prev.observed_at,
                to_time=cur.observed_at,
                before_score=prev.stance_score,
                after_score=cur.stance_score,
                delta=delta,
                before_summary=prev.summary,
                after_summary=cur.summary,
                evidence_memory_ids=[prev.memory_id, cur.memory_id],
                possible_causes=self._infer_causes(prev, cur),
                confidence_score=min(0.95, mean([prev.confidence_score, cur.confidence_score]) + abs(delta) * 0.2),
            )
            if not dry_run:
                shift.memory_id = await self.persist_shift(shift)
            shifts.append(shift)
        return shifts

    async def scan_all(self, *, since: datetime | None = None, dry_run: bool = True) -> list[OpinionShift]:
        rows = await self.repository.db.fetchall("SELECT DISTINCT entity_id FROM memory_entities LIMIT 1000;")
        all_shifts: list[OpinionShift] = []
        for row in rows:
            all_shifts.extend(await self.scan_entity(entity_id=str(row["entity_id"]), start=since, dry_run=dry_run))
        return all_shifts

    async def persist_observation(self, obs: OpinionObservation) -> str:
        obs_id = uuid4().hex
        await self.repository.db.execute(
            """
            INSERT OR REPLACE INTO opinion_observations(
                id, memory_id, entity_id, observed_at, stance_score, sentiment_score,
                aspect, summary, evidence_text, confidence_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (obs_id, obs.memory_id, obs.entity_id, _iso(obs.observed_at), obs.stance_score, obs.sentiment_score,
             obs.aspect, obs.summary, obs.evidence_text, obs.confidence_score),
        )
        return obs_id

    async def persist_shift(self, shift: OpinionShift) -> str:
        content = (
            f"对实体 {shift.entity_id} 的观点发生变化："
            f"从 {shift.before_summary[:160]} 变为 {shift.after_summary[:160]}。"
            f"变化幅度 {shift.delta:.2f}。"
        )
        memory_id = shift.memory_id or uuid4().hex
        record = MemoryRecord(
            id=memory_id,
            memory_type="OPINION_SHIFT",
            content=content,
            content_summary=content[:240],
            importance_score=min(1.0, 0.65 + abs(shift.delta) * 0.35),
            confidence_score=shift.confidence_score,
            metadata_json=json.dumps({
                "scope": "global",
                "tags": ["opinion_shift", "timeline"],
                "entities": [shift.entity_id],
                "evidence_memory_ids": shift.evidence_memory_ids,
            }, ensure_ascii=False, sort_keys=True),
        )
        await self.repository.store_memory(record)
        await self.repository.db.execute(
            """
            INSERT OR REPLACE INTO opinion_shifts(
                id, memory_id, entity_id, from_time, to_time, before_score, after_score, delta,
                before_summary, after_summary, possible_causes_json, evidence_memory_ids_json,
                confidence_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (uuid4().hex, memory_id, shift.entity_id, _iso(shift.from_time), _iso(shift.to_time),
             shift.before_score, shift.after_score, shift.delta, shift.before_summary, shift.after_summary,
             json.dumps(shift.possible_causes, ensure_ascii=False), json.dumps(shift.evidence_memory_ids, ensure_ascii=False),
             shift.confidence_score),
        )
        return memory_id

    async def _load_or_extract(
        self,
        *,
        entity_id: str,
        start: datetime | None,
        end: datetime | None,
        dry_run: bool,
    ) -> list[OpinionObservation]:
        clauses = ["entity_id = ?"]
        params: list[Any] = [entity_id]
        if start:
            clauses.append("observed_at >= ?")
            params.append(_iso(start))
        if end:
            clauses.append("observed_at <= ?")
            params.append(_iso(end))
        rows = await self.repository.db.fetchall(
            f"SELECT * FROM opinion_observations WHERE {' AND '.join(clauses)} ORDER BY observed_at ASC;",
            tuple(params),
        )
        observations = [OpinionObservation(
            memory_id=str(r["memory_id"]), entity_id=str(r["entity_id"]), observed_at=_dt(r["observed_at"]),
            stance_score=float(r["stance_score"]), sentiment_score=float(r["sentiment_score"]), aspect=r["aspect"],
            summary=str(r["summary"]), evidence_text=r["evidence_text"], confidence_score=float(r["confidence_score"]),
        ) for r in rows]
        if observations:
            return observations

        mem_rows = await self.repository.db.fetchall(
            """
            SELECT m.* FROM memory_entities me JOIN memories m ON m.id = me.memory_id
            WHERE me.entity_id = ? AND m.active_state = 'active'
            ORDER BY COALESCE(m.valid_from, m.created_at, m.updated_at) ASC;
            """,
            (entity_id,),
        )
        for row in mem_rows:
            obs = await self.extractor.extract(memory=dict(row), entity_id=entity_id)
            if obs:
                observations.append(obs)
                if not dry_run:
                    await self.persist_observation(obs)
        return observations

    def _infer_causes(self, before: OpinionObservation, after: OpinionObservation) -> list[str]:
        causes = []
        if before.aspect and after.aspect and before.aspect != after.aspect:
            causes.append(f"评价维度从 {before.aspect} 转向 {after.aspect}")
        if abs(after.stance_score) < abs(before.stance_score):
            causes.append("后续表述更中性，可能因补充证据或体验变复杂")
        elif abs(after.stance_score) > abs(before.stance_score):
            causes.append("后续表述更强烈，可能因重复体验强化了判断")
        if not causes:
            causes.append("从同一实体的不同时间记忆中观察到评价分数显著变化")
        return causes
