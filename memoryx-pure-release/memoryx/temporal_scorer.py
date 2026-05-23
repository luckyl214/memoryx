"""P4: TemporalScorer — 时序感知评分。

区分 current/past/future 查询意图：
- expired memory 对 current query 降权
- historical memory 对 past query 加权
- upsert_state() 支持状态覆盖和 supersede
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class TemporalQueryIntent:
    """时序查询意图。"""
    intent: str  # current, past, future
    reference_time: datetime | None = None


class TemporalScorer:
    """时序评分器。

    基于 memory 的 valid_from / valid_to 计算时序相关性。
    """

    # 衰减常数（天）
    DECAY_HALF_LIFE_DAYS: float = 90.0

    def __init__(self, *, repository=None) -> None:
        self.repository = repository

    async def score(
        self,
        memory: dict[str, Any],
        intent: TemporalQueryIntent | None = None,
    ) -> float:
        """计算单条 memory 的时序分数 (0.0–1.0)。"""
        now = intent.reference_time if intent and intent.reference_time else datetime.now(timezone.utc)

        valid_from = self._parse_dt(memory.get("valid_from"))
        valid_to = self._parse_dt(memory.get("valid_to"))

        base_score = self._time_decay(valid_from or now, now)

        if intent is None or intent.intent == "current":
            # Expired memories get heavy penalty
            if valid_to and valid_to < now:
                return base_score * 0.1
            return base_score

        elif intent.intent == "past":
            # Prefer memories from around that time
            if valid_from and valid_to:
                mid = valid_from + (valid_to - valid_from) / 2
                dist_days = abs((now - mid).days)
                return max(0.0, 1.0 - dist_days / 365.0)
            return base_score

        elif intent.intent == "future":
            # Future-intent: prefer recent memories
            return base_score

        return base_score

    def classify_intent(self, query: str) -> TemporalQueryIntent:
        """从查询文本推断时序意图。"""
        lowered = query.lower()
        past_words = {"was", "did", "had", "last week", "yesterday", "ago", "before", "previously", "历史", "以前"}
        future_words = {"will", "plan", "planning", "next", "tomorrow", "future", "计划", "将要"}

        past_hits = sum(1 for w in past_words if w in lowered)
        future_hits = sum(1 for w in future_words if w in lowered)

        if past_hits > future_hits:
            return TemporalQueryIntent(intent="past")
        elif future_hits > 0:
            return TemporalQueryIntent(intent="future")
        return TemporalQueryIntent(intent="current")

    def _time_decay(self, dt: datetime, now: datetime) -> float:
        # Ensure both are offset-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        days = max(0.0, (now - dt).total_seconds() / 86400.0)
        return max(0.0, 0.5 ** (days / self.DECAY_HALF_LIFE_DAYS))

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            s = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    async def upsert_state(self, memory_id: str, active_state: str) -> None:
        """更新 memory 的 active_state（覆盖 / supersede）。"""
        if self.repository:
            await self.repository.db.execute(
                "UPDATE memories SET active_state = ?, updated_at = datetime('now') WHERE id = ?;",
                (active_state, memory_id),
            )
