from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4


class ImportanceReinforcementEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def run_cycle(
        self,
        *,
        project_keywords: list[str] | None = None,
        now_iso: str | None = None,
    ) -> int:
        memories = await self.repository.list_active_memories(limit=1000)
        now = self._parse_dt(now_iso) if now_iso else datetime.now(timezone.utc)
        keywords = [item.lower() for item in (project_keywords or []) if item]
        content_counts = self._content_counts(memories)
        updated = 0

        for memory in memories:
            memory_id = str(memory["memory_id"])
            delta = 0.0
            reasons: list[str] = []

            access_count = int(memory.get("access_count", 0))
            if access_count >= 5:
                delta += 0.18
                reasons.append("access")
            elif access_count >= 3:
                delta += 0.10
                reasons.append("access")

            content_key = str(memory.get("content", "")).strip().lower()
            if content_counts.get(content_key, 0) >= 2:
                delta += 0.12
                reasons.append("recurrence")

            content = str(memory.get("content", "")).lower()
            scope = str(memory.get("scope", "")).lower()
            entities = self._parse_entities(memory.get("entities_json", "[]"))
            if keywords and self._matches_project(keywords, content, scope, entities):
                delta += 0.14
                reasons.append("project_relevance")

            memory_type = str(memory.get("memory_type", "")).upper()
            importance = float(memory.get("importance_score", 0.0))
            if memory_type in {"PREFERENCE", "PROJECT"} and importance >= 0.7:
                delta += 0.06
                reasons.append("user_priority")

            if any(token in content for token in ("frustrated", "urgent", "critical", "blocked", "incident")):
                delta += 0.05
                reasons.append("emotional")

            current_score = float(memory.get("reinforcement_score", 0.0))
            if delta > 0:
                new_score = min(1.0, current_score + delta)
                await self.repository.db.execute(
                    "UPDATE memories SET reinforcement_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                    (new_score, memory_id),
                )
                await self.repository.db.execute(
                    "INSERT INTO reinforcement_events(reinforcement_id, memory_id, reinforcement_type, score_delta, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
                    (uuid4().hex, memory_id, "+".join(reasons) or "reinforcement", delta),
                )
                updated += 1

            decay_delta = self._decay_delta(memory, now)
            if decay_delta > 0:
                current_decay = float(memory.get("decay_score", 0.0))
                new_decay = min(1.0, current_decay + decay_delta)
                await self.repository.db.execute(
                    "UPDATE memories SET decay_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                    (new_decay, memory_id),
                )
                if delta == 0:
                    updated += 1

        return updated

    def _content_counts(self, memories: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for memory in memories:
            key = str(memory.get("content", "")).strip().lower()
            if key:
                counts[key] = counts.get(key, 0) + 1
        return counts

    def _parse_entities(self, raw: object) -> list[str]:
        if isinstance(raw, list):
            return [str(item).lower() for item in raw]
        try:
            parsed = json.loads(str(raw or "[]"))
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).lower() for item in parsed]

    def _matches_project(self, keywords: list[str], content: str, scope: str, entities: list[str]) -> bool:
        haystacks = [content, scope, " ".join(entities)]
        return any(keyword in hay for keyword in keywords for hay in haystacks)

    def _decay_delta(self, memory: dict, now: datetime) -> float:
        valid_from = memory.get("valid_from")
        if not valid_from:
            return 0.0
        dt = self._parse_dt(str(valid_from))
        age_days = max(0.0, (now - dt).total_seconds() / 86400)
        if age_days < 180:
            return 0.0
        access_count = int(memory.get("access_count", 0))
        reinforcement_score = float(memory.get("reinforcement_score", 0.0))
        if access_count >= 3 or reinforcement_score >= 0.7:
            return 0.0
        return min(0.2, age_days / 3650)

    def _parse_dt(self, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
