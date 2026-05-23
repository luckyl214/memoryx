from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MetaCognitiveObservation:
    task: str
    strategy: str
    confidence: float
    outcome: str
    notes: str = ""
    corrected_assumption: str = ""


@dataclass(slots=True)
class MetaCognitiveProfile:
    session_id: str
    current_task: str = ""
    average_confidence: float = 0.0
    confidence_trend: str = "steady"
    reasoning_quality: str = "unknown"
    corrected_assumptions: list[str] = field(default_factory=list)
    successful_strategies: list[str] = field(default_factory=list)
    failed_strategies: list[str] = field(default_factory=list)
    repeated_failures: list[str] = field(default_factory=list)
    recommended_strategies: list[str] = field(default_factory=list)
    self_improvement_lessons: list[str] = field(default_factory=list)
    adaptation_signals: list[str] = field(default_factory=list)
    recent_notes: list[str] = field(default_factory=list)
