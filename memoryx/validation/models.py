from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from memoryx.extraction import ExtractionMemory


class ValidationDecision(StrEnum):
    ACCEPT = "ACCEPT"
    MERGE = "MERGE"
    CONFLICT = "CONFLICT"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


@dataclass(slots=True)
class ValidationResult:
    decision: ValidationDecision
    quality_score: float
    reasons: list[str] = field(default_factory=list)
    matched_memory: ExtractionMemory | None = None
    merged_memory: ExtractionMemory | None = None
    safety_flags: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    conflict_with: str | None = None
