from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from memoryx.extraction import ExtractionMemory

from .similarity_engine import SimilarityEngine


@dataclass(slots=True)
class DedupMatch:
    matched_memory: ExtractionMemory
    similarity: float


class DedupEngine:
    def __init__(self, similarity_engine: SimilarityEngine | None = None, threshold: float = 0.85) -> None:
        self.similarity_engine = similarity_engine or SimilarityEngine()
        self.threshold = threshold

    def find_duplicate(self, candidate: ExtractionMemory, existing_memories: Iterable[ExtractionMemory]) -> DedupMatch | None:
        best_match: DedupMatch | None = None
        for memory in existing_memories:
            similarity = self.similarity_engine.similarity(candidate.content, memory.content)
            if similarity >= self.threshold and (best_match is None or similarity > best_match.similarity):
                best_match = DedupMatch(matched_memory=memory, similarity=similarity)
        return best_match
