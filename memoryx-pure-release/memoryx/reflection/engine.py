from __future__ import annotations

from collections import Counter, defaultdict
from uuid import uuid4


class ReflectionEngine:
    def __init__(self, *, repository) -> None:
        self.repository = repository

    async def generate_reflection(self) -> dict:
        memories = await self.repository.list_memories(limit=1000)

        stable_preferences = self._stable_preferences(memories)
        recurring_issues = self._recurring_issues(memories)
        project_evolution = self._project_evolution(memories)
        workflow_patterns = self._workflow_patterns(memories)
        trend_signals = self._trend_signals(memories)

        summary_parts = []
        if stable_preferences:
            summary_parts.append(f"Stable preferences: {'; '.join(stable_preferences[:3])}")
        if recurring_issues:
            summary_parts.append(f"Recurring issues: {'; '.join(recurring_issues[:3])}")
        if project_evolution:
            summary_parts.append(f"Project evolution: {'; '.join(project_evolution[:3])}")
        if workflow_patterns:
            summary_parts.append(f"Workflow patterns: {'; '.join(workflow_patterns[:3])}")
        if trend_signals:
            summary_parts.append(f"Trends: {'; '.join(trend_signals[:3])}")
        summary = " | ".join(summary_parts) if summary_parts else "No long-term reflection patterns detected."

        await self.repository.db.execute(
            "INSERT INTO reflection_summaries(id, summary, content_hash, checksum, valid_from, active_state, created_at, metadata_json) VALUES (?, ?, ?, ?, datetime('now'), 'active', datetime('now'), ?);",
            (uuid4().hex, summary, self.repository.checksum(summary), self.repository.checksum(summary), "{}"),
        )

        return {
            "stable_preferences": stable_preferences,
            "recurring_issues": recurring_issues,
            "project_evolution": project_evolution,
            "workflow_patterns": workflow_patterns,
            "trend_signals": trend_signals,
            "summary": summary,
        }

    def _stable_preferences(self, memories: list[dict]) -> list[str]:
        prefs = [str(item.get("content", "")).strip() for item in memories if str(item.get("memory_type", "")).upper() == "PREFERENCE"]
        counts = Counter(prefs)
        return [text for text, count in counts.items() if text and count >= 2]

    def _recurring_issues(self, memories: list[dict]) -> list[str]:
        issue_tokens = ("incident", "rollback", "error", "failed", "failure", "timeout", "bug")
        issue_texts = [str(item.get("content", "")).strip() for item in memories if any(token in str(item.get("content", "")).lower() for token in issue_tokens)]
        grouped: dict[str, int] = defaultdict(int)
        for text in issue_texts:
            lowered = text.lower()
            if "deployment" in lowered and "incident" in lowered:
                grouped["deployment incident pattern"] += 1
            elif "rollback" in lowered:
                grouped["rollback pattern"] += 1
            else:
                grouped[text] += 1
        return [label for label, count in grouped.items() if count >= 2]

    def _project_evolution(self, memories: list[dict]) -> list[str]:
        projects = [item for item in memories if str(item.get("memory_type", "")).upper() == "PROJECT"]
        ordered = sorted(projects, key=lambda item: str(item.get("valid_from") or item.get("updated_at") or item.get("created_at") or ""))
        return [str(item.get("content", "")).strip() for item in ordered if str(item.get("content", "")).strip()]

    def _workflow_patterns(self, memories: list[dict]) -> list[str]:
        patterns: list[str] = []
        for item in memories:
            content = str(item.get("content", "")).strip()
            tags = str(item.get("metadata_json", "{}")).lower()
            if "workflow" in tags or any(token in content.lower() for token in ("async queue", "retry", "backoff", "graceful shutdown")):
                patterns.append(content)
        return patterns[:5]

    def _trend_signals(self, memories: list[dict]) -> list[str]:
        type_counts = Counter(str(item.get("memory_type", "")).upper() for item in memories)
        ranked = sorted(type_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        return [f"{memory_type}:{count}" for memory_type, count in ranked[:5] if memory_type]
