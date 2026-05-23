from __future__ import annotations

from collections.abc import Iterable

from memoryx.extraction import ExtractionMemory

from .conflict_resolver import ConflictResolver
from .dedup_engine import DedupEngine
from .models import ValidationDecision, ValidationResult
from .quarantine_manager import QuarantineManager
from .scoring_engine import ScoringEngine
from .similarity_engine import SimilarityEngine


class MemoryValidationEngine:
    def __init__(
        self,
        *,
        min_confidence: float = 0.4,
        min_importance: float = 0.3,
        dedup_threshold: float = 0.85,
        quarantine_threshold: float = 0.65,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_importance = min_importance
        self.scoring = ScoringEngine()
        self.similarity = SimilarityEngine()
        self.dedup = DedupEngine(self.similarity, threshold=dedup_threshold)
        self.conflict = ConflictResolver()
        self.quarantine = QuarantineManager(threshold=quarantine_threshold)

    def validate_candidate(self, candidate: ExtractionMemory, existing_memories: Iterable[ExtractionMemory]) -> ValidationResult:
        existing = list(existing_memories)
        quality_score = self.scoring.score(candidate)
        reasons: list[str] = []

        report = self.quarantine.inspect(candidate)
        if report.should_quarantine:
            return ValidationResult(
                decision=ValidationDecision.QUARANTINE,
                quality_score=quality_score,
                reasons=["suspicious memory detected", *report.flags],
                safety_flags=report.flags,
            )

        if candidate.confidence_score < self.min_confidence:
            reasons.append("confidence below threshold")
            return ValidationResult(ValidationDecision.REJECT, quality_score, reasons)

        if candidate.importance_score < self.min_importance:
            reasons.append("importance below threshold")
            return ValidationResult(ValidationDecision.REJECT, quality_score, reasons)

        duplicate = self.dedup.find_duplicate(candidate, existing)
        if duplicate is not None:
            reasons.append("duplicate memory detected")
            return ValidationResult(
                decision=ValidationDecision.MERGE,
                quality_score=quality_score,
                reasons=reasons,
                matched_memory=duplicate.matched_memory,
                merged_memory=candidate,
                duplicate_of=duplicate.matched_memory.source_message_id,
            )

        conflict = self.conflict.resolve(candidate, existing)
        if conflict is not None:
            reasons.append(conflict.reason)
            return ValidationResult(
                decision=ValidationDecision.CONFLICT,
                quality_score=quality_score,
                reasons=reasons,
                matched_memory=conflict.conflicting_memory,
                conflict_with=conflict.conflicting_memory.source_message_id,
            )

        return ValidationResult(ValidationDecision.ACCEPT, quality_score, reasons)
