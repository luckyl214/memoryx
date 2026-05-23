from __future__ import annotations

from memoryx.extraction import ExtractionMemory


class ScoringEngine:
    def score(self, memory: ExtractionMemory) -> float:
        score = (memory.importance_score * 0.45) + (memory.confidence_score * 0.35)
        if memory.tags:
            score += 0.05
        if memory.entities:
            score += 0.05
        if memory.scope in {"user", "project"}:
            score += 0.1
        return min(1.0, score)
