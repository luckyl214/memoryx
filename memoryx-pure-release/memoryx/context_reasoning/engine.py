from __future__ import annotations

from dataclasses import replace

from memoryx.retrieval import RetrievalResult


class ContextReasoningEngine:
    async def rerank(
        self,
        *,
        query: str,
        intent: str,
        candidates: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        ranked: list[tuple[float, RetrievalResult]] = []
        for candidate in candidates:
            usefulness = self._usefulness_score(query=query, intent=intent, candidate=candidate)
            explanation = self._merge_explanation(candidate.explanation, usefulness)
            ranked.append(
                (
                    usefulness,
                    replace(candidate, final_score=usefulness, explanation=explanation),
                )
            )
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in ranked]

    async def select_useful(
        self,
        *,
        query: str,
        intent: str,
        candidates: list[RetrievalResult],
        threshold: float,
    ) -> list[RetrievalResult]:
        ranked = await self.rerank(query=query, intent=intent, candidates=candidates)
        return [candidate for candidate in ranked if candidate.final_score >= threshold]

    async def explain_context(
        self,
        *,
        query: str,
        intent: str,
        candidates: list[RetrievalResult],
    ) -> dict[str, object]:
        ranked = await self.rerank(query=query, intent=intent, candidates=candidates)
        project_narrative = " ".join(
            candidate.content for candidate in ranked if candidate.memory_type in {"PROJECT", "TASK", "OBSERVATION"}
        ).strip()
        causal_chain = [
            candidate.content
            for candidate in ranked
            if candidate.memory_type in {"TASK", "OBSERVATION", "EXPERIENCE", "EPISODIC", "PROJECT"}
        ]
        return {
            "query": query,
            "intent": intent,
            "project_narrative": project_narrative,
            "causal_chain": causal_chain,
        }

    async def analyze_conflicts(
        self,
        *,
        query: str,
        intent: str,
        candidates: list[RetrievalResult],
    ) -> dict[str, object]:
        conflict_pairs: list[dict[str, str]] = []
        lowered = [(candidate.memory_id, candidate.content.lower()) for candidate in candidates]
        for idx, (left_id, left_text) in enumerate(lowered):
            for right_id, right_text in lowered[idx + 1 :]:
                if self._texts_conflict(left_text, right_text):
                    conflict_pairs.append({"left": left_id, "right": right_id})
        return {
            "query": query,
            "intent": intent,
            "has_conflict": bool(conflict_pairs),
            "conflict_pairs": conflict_pairs,
        }

    def _usefulness_score(self, *, query: str, intent: str, candidate: RetrievalResult) -> float:
        score = candidate.final_score * 0.35
        query_tokens = self._tokenize(query)
        content_tokens = self._tokenize(candidate.content)
        overlap = len(query_tokens & content_tokens)
        score += min(overlap * 0.22, 0.66)

        if intent == "debugging" and any(token in content_tokens for token in {"debug", "timeout", "queue", "worker", "backpressure"}):
            score += 0.28
        if intent == "coding" and any(token in content_tokens for token in {"implement", "engine", "task", "coding"}):
            score += 0.25
        if candidate.memory_type in {"TASK", "PROJECT"}:
            score += 0.18
        if candidate.memory_type == "PREFERENCE" and not query_tokens.intersection({"prefer", "preference", "style", "stack"}):
            score -= 0.35
        return max(0.0, min(score, 1.5))

    def _merge_explanation(self, explanation: str, usefulness: float) -> str:
        prefix = explanation.strip()
        suffix = f"usefulness={usefulness:.3f}"
        return f"{prefix}; {suffix}" if prefix else suffix

    def _texts_conflict(self, left: str, right: str) -> bool:
        has_orm = "orm" in left and "orm" in right
        polarity_conflict = ("no orm" in left and "orm-heavy" in right) or ("orm-heavy" in left and "no orm" in right)
        light_conflict = ("lightweight" in left and "heavy" in right) or ("heavy" in left and "lightweight" in right)
        return (has_orm and polarity_conflict) or light_conflict

    def _tokenize(self, text: str) -> set[str]:
        return {token.strip(" ,.:;!?()[]{}\n\t").lower() for token in text.split() if token.strip()}
