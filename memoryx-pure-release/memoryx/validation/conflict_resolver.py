from __future__ import annotations

from dataclasses import dataclass

from memoryx.extraction import ExtractionMemory


@dataclass(slots=True)
class ConflictMatch:
    conflicting_memory: ExtractionMemory
    reason: str


class ConflictResolver:
    def resolve(self, candidate: ExtractionMemory, existing_memories: list[ExtractionMemory]) -> ConflictMatch | None:
        candidate_text = candidate.content.lower()
        for memory in existing_memories:
            text = memory.content.lower()
            if self._is_contradiction(candidate_text, text):
                return ConflictMatch(conflicting_memory=memory, reason="semantic contradiction detected")
        return None

    def _is_contradiction(self, a: str, b: str) -> bool:
        negative_markers = ("dislike", "dislikes", "hate", "not", "never", "no longer", "opposite", "ignore")
        positive_markers = ("like", "prefer", "love", "use", "want", "choose")
        return (
            any(marker in a for marker in negative_markers) and any(marker in b for marker in positive_markers)
        ) or (
            any(marker in b for marker in negative_markers) and any(marker in a for marker in positive_markers)
        )
