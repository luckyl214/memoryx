from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class DistilledKnowledgeArtifact:
    stable_preferences: list[str] = field(default_factory=list)
    long_term_profile: list[str] = field(default_factory=list)
    repetitive_patterns: list[str] = field(default_factory=list)
    project_principles: list[str] = field(default_factory=list)
    coding_habits: list[str] = field(default_factory=list)
    semantic_abstractions: list[str] = field(default_factory=list)
    source_count: int = 0
    summary: str = ""


class KnowledgeDistillationEngine:
    def __init__(self, *, repository, min_repetitions: int = 2) -> None:
        self.repository = repository
        self.min_repetitions = min_repetitions

    async def distill(self, *, persist: bool = False, limit: int = 1000) -> DistilledKnowledgeArtifact:
        memories = await self.repository.list_active_memories(limit=limit)
        artifact = DistilledKnowledgeArtifact(
            stable_preferences=self._stable_preferences(memories),
            repetitive_patterns=self._repetitive_patterns(memories),
            project_principles=self._project_principles(memories),
            coding_habits=self._coding_habits(memories),
            source_count=len(memories),
        )
        artifact.long_term_profile = self._long_term_profile(artifact)
        artifact.semantic_abstractions = self._semantic_abstractions(artifact)
        artifact.summary = self._summary(artifact)

        if persist:
            content_hash = hashlib.sha256(artifact.summary.encode()).hexdigest()
            await self.repository.db.execute(
                "INSERT INTO reflection_summaries(id, summary, content_hash, checksum, created_at, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
                (uuid4().hex, artifact.summary, content_hash, content_hash),
            )
        return artifact

    def _stable_preferences(self, memories: list[dict]) -> list[str]:
        preferences = [
            self._content(item)
            for item in memories
            if str(item.get("memory_type", "")).upper() == "PREFERENCE" and self._quality_ok(item)
        ]
        counts = Counter(preferences)
        return [text for text, count in counts.items() if text and count >= self.min_repetitions]

    def _repetitive_patterns(self, memories: list[dict]) -> list[str]:
        normalized = [self._normalize(self._content(item)) for item in memories if self._content(item)]
        counts = Counter(normalized)
        return [pattern for pattern, count in counts.items() if count >= self.min_repetitions]

    def _project_principles(self, memories: list[dict]) -> list[str]:
        principles = []
        for item in memories:
            content = self._content(item)
            lowered = content.lower()
            if str(item.get("scope", "")).lower() == "project" and any(
                token in lowered for token in ("principle", "avoid", "must", "prefer", "architecture")
            ):
                principles.append(content)
        return self._unique(principles)

    def _coding_habits(self, memories: list[dict]) -> list[str]:
        habits = []
        for item in memories:
            content = self._content(item)
            lowered = content.lower()
            tags = str(item.get("tags_json", "[]")).lower()
            if "workflow" in tags or any(
                token in lowered for token in ("inspect real", "red test", "debugging pattern", "before patching", "async queue")
            ):
                habits.append(content)
        return self._unique(habits)

    def _long_term_profile(self, artifact: DistilledKnowledgeArtifact) -> list[str]:
        profile = []
        profile.extend(artifact.stable_preferences)
        profile.extend(artifact.project_principles[:3])
        profile.extend(artifact.coding_habits[:3])
        return self._unique(profile)

    def _semantic_abstractions(self, artifact: DistilledKnowledgeArtifact) -> list[str]:
        abstractions = []
        if artifact.stable_preferences:
            abstractions.append(f"stable_preferences:{len(artifact.stable_preferences)}")
        if artifact.project_principles:
            abstractions.append(f"project_principles:{len(artifact.project_principles)}")
        if artifact.coding_habits:
            abstractions.append(f"coding_habits:{len(artifact.coding_habits)}")
        if artifact.repetitive_patterns:
            abstractions.append(f"repetitive_patterns:{len(artifact.repetitive_patterns)}")
        return abstractions

    def _summary(self, artifact: DistilledKnowledgeArtifact) -> str:
        parts = []
        if artifact.stable_preferences:
            parts.append("preferences=" + "; ".join(artifact.stable_preferences[:3]))
        if artifact.project_principles:
            parts.append("principles=" + "; ".join(artifact.project_principles[:3]))
        if artifact.coding_habits:
            parts.append("habits=" + "; ".join(artifact.coding_habits[:3]))
        if not parts:
            return "Stable profile: no durable distilled knowledge yet."
        return "Stable profile: " + " | ".join(parts)

    def _quality_ok(self, item: dict) -> bool:
        return float(item.get("confidence_score", 0.0)) >= 0.75 and float(item.get("importance_score", 0.0)) >= 0.6

    def _content(self, item: dict) -> str:
        return str(item.get("content", "")).strip()

    def _normalize(self, value: str) -> str:
        return " ".join(value.lower().split())

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
