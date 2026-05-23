from __future__ import annotations

from collections import Counter


class SimilarityEngine:
    def similarity(self, left: str, right: str) -> float:
        left_tokens = self._tokens(left)
        right_tokens = self._tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        left_counts = Counter(left_tokens)
        right_counts = Counter(right_tokens)
        intersection = sum(min(left_counts[token], right_counts[token]) for token in left_counts.keys() | right_counts.keys())
        union = sum(max(left_counts[token], right_counts[token]) for token in left_counts.keys() | right_counts.keys())
        if not union:
            return 0.0
        return intersection / union

    def _tokens(self, text: str) -> list[str]:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
        return [token for token in normalized.split() if token]
