from __future__ import annotations

import asyncio
from collections import Counter

from .models import MetaCognitiveObservation, MetaCognitiveProfile


class MetaCognitiveReflectionEngine:
    def __init__(self) -> None:
        self._observations: dict[str, list[MetaCognitiveObservation]] = {}
        self._lock = asyncio.Lock()

    async def record_observation(
        self,
        *,
        session_id: str,
        task: str,
        strategy: str,
        confidence: float,
        outcome: str,
        notes: str = "",
        corrected_assumption: str = "",
    ) -> MetaCognitiveObservation:
        observation = MetaCognitiveObservation(
            task=task,
            strategy=strategy,
            confidence=max(0.0, min(confidence, 1.0)),
            outcome=outcome.strip().lower(),
            notes=notes.strip(),
            corrected_assumption=corrected_assumption.strip(),
        )
        async with self._lock:
            self._observations.setdefault(session_id, []).append(observation)
        return observation

    async def get_profile(self, *, session_id: str) -> MetaCognitiveProfile:
        async with self._lock:
            observations = list(self._observations.get(session_id, []))
        return self._build_profile(session_id=session_id, observations=observations)

    async def summarize_session(self, *, session_id: str) -> str:
        profile = await self.get_profile(session_id=session_id)
        parts: list[str] = []
        if profile.current_task:
            parts.append(f"task={profile.current_task}")
        if profile.successful_strategies:
            parts.append("success=" + ", ".join(profile.successful_strategies[:2]))
        if profile.failed_strategies:
            parts.append("fail=" + ", ".join(profile.failed_strategies[:2]))
        parts.append(f"confidence={profile.average_confidence:.2f} ({profile.confidence_trend})")
        if profile.corrected_assumptions:
            parts.append("corrections=" + "; ".join(profile.corrected_assumptions[:2]))
        if profile.adaptation_signals:
            parts.append("signals=" + "; ".join(profile.adaptation_signals[:2]))
        if profile.recent_notes:
            parts.append("notes=" + "; ".join(profile.recent_notes[:2]))
        return " | ".join(parts) if parts else "No meta-cognitive reflection recorded."

    async def self_improvement_summary(self, *, session_id: str) -> str:
        profile = await self.get_profile(session_id=session_id)
        if not profile.current_task:
            return "No meta-cognitive reflection recorded."

        parts = [
            f"task={profile.current_task}",
            f"reasoning_quality={profile.reasoning_quality}",
        ]
        if profile.recommended_strategies:
            parts.append("recommended=" + ", ".join(profile.recommended_strategies[:3]))
        if profile.self_improvement_lessons:
            parts.append("lessons=" + "; ".join(profile.self_improvement_lessons[:3]))
        if profile.repeated_failures:
            parts.append("avoid=" + ", ".join(profile.repeated_failures[:3]))
        return " | ".join(parts)

    def _build_profile(self, *, session_id: str, observations: list[MetaCognitiveObservation]) -> MetaCognitiveProfile:
        if not observations:
            return MetaCognitiveProfile(session_id=session_id)

        confidences = [item.confidence for item in observations]
        average_confidence = sum(confidences) / len(confidences)
        confidence_trend = self._confidence_trend(confidences)

        corrected_assumptions = self._unique_preserving_order(
            item.corrected_assumption for item in observations if item.corrected_assumption
        )
        successful_strategies = self._strategies_by_outcome(observations, outcome="succeeded")
        failed_strategies = self._strategies_by_outcome(observations, outcome="failed")
        repeated_failures = self._repeated_failures(observations)
        reasoning_quality = self._reasoning_quality(observations)
        recommended_strategies = self._recommended_strategies(observations)
        self_improvement_lessons = self._self_improvement_lessons(observations)
        adaptation_signals = self._adaptation_signals(observations)
        recent_notes = [item.notes for item in observations if item.notes][-3:]

        return MetaCognitiveProfile(
            session_id=session_id,
            current_task=observations[-1].task,
            average_confidence=average_confidence,
            confidence_trend=confidence_trend,
            reasoning_quality=reasoning_quality,
            corrected_assumptions=corrected_assumptions,
            successful_strategies=successful_strategies,
            failed_strategies=failed_strategies,
            repeated_failures=repeated_failures,
            recommended_strategies=recommended_strategies,
            self_improvement_lessons=self_improvement_lessons,
            adaptation_signals=adaptation_signals,
            recent_notes=recent_notes,
        )

    def _confidence_trend(self, confidences: list[float]) -> str:
        if len(confidences) < 2:
            return "steady"
        delta = confidences[-1] - confidences[0]
        if delta > 0.1:
            return "rising"
        if delta < -0.1:
            return "falling"
        return "steady"

    def _strategies_by_outcome(
        self,
        observations: list[MetaCognitiveObservation],
        *,
        outcome: str,
    ) -> list[str]:
        counter = Counter(item.strategy for item in observations if item.outcome == outcome)
        ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
        return [strategy for strategy, _count in ranked]

    def _adaptation_signals(self, observations: list[MetaCognitiveObservation]) -> list[str]:
        signals: list[str] = []
        for left, right in zip(observations, observations[1:]):
            if left.outcome == "failed" and right.strategy != left.strategy:
                signals.append(f"pivoted from {left.strategy} to {right.strategy}")
            if left.confidence < 0.5 and right.confidence - left.confidence > 0.2:
                signals.append(f"confidence recovery after {left.strategy}")
        return self._unique_preserving_order(signals)

    def _repeated_failures(self, observations: list[MetaCognitiveObservation]) -> list[str]:
        counter = Counter(item.strategy for item in observations if item.outcome == "failed")
        repeated = [strategy for strategy, count in counter.items() if count > 1]
        return sorted(repeated)

    def _reasoning_quality(self, observations: list[MetaCognitiveObservation]) -> str:
        if not observations:
            return "unknown"
        failures = sum(1 for item in observations if item.outcome == "failed")
        successes = sum(1 for item in observations if item.outcome == "succeeded")
        repeated_failures = len(self._repeated_failures(observations))
        overconfident_failures = sum(
            1 for item in observations if item.outcome == "failed" and item.confidence >= 0.75
        )

        if repeated_failures or overconfident_failures:
            return "needs_correction"
        if successes and failures == 0:
            return "strong"
        if successes >= failures:
            return "improving"
        return "unstable"

    def _recommended_strategies(self, observations: list[MetaCognitiveObservation]) -> list[str]:
        successful = [item.strategy for item in observations if item.outcome == "succeeded"]
        return self._unique_preserving_order(successful)

    def _self_improvement_lessons(self, observations: list[MetaCognitiveObservation]) -> list[str]:
        lessons = []
        for item in observations:
            if item.corrected_assumption:
                lessons.append(item.corrected_assumption)
            if item.outcome == "succeeded" and item.notes:
                lessons.append(item.notes)
        return self._unique_preserving_order(lessons)

    def _unique_preserving_order(self, values) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
