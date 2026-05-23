from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class FeedbackEvent:
    memory_id: str
    positive: bool
    session_id: str | None = None
    reason: str = ""
    source: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PropagationCandidate:
    memory_id: str
    score: float
    keyword_similarity: float = 0.0
    semantic_similarity: float = 0.0
    entity_overlap: float = 0.0
    graph_distance: int | None = None
    confidence_delta: float = 0.0
    applied: bool = False
    reason: str = ""


@dataclass(slots=True)
class PropagationResult:
    root_memory_id: str
    feedback_event_id: str | None = None
    root_delta: float = 0.0
    affected: list[PropagationCandidate] = field(default_factory=list)
    lesson_created: str | None = None
    dry_run: bool = True


@dataclass(slots=True)
class LessonSpec:
    lesson_text: str
    policy_type: str = "warn"
    severity: float = 0.5
    trigger_intents: list[str] = field(default_factory=list)
    trigger_patterns: list[str] = field(default_factory=list)
    prohibited_patterns: list[str] = field(default_factory=list)
    recommended_action: str = ""
    evidence_memory_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LessonMatch:
    lesson_id: str
    memory_id: str
    lesson_text: str
    policy_type: str
    severity: float
    confidence_score: float
    match_score: float
    recommended_action: str = ""
    evidence_count: int = 0


@dataclass(slots=True)
class TaskDuration:
    task_id: str | None
    session_id: str | None
    entity_id: str | None
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    source: str = "event"
    confidence_score: float = 1.0


@dataclass(slots=True)
class OpinionObservation:
    memory_id: str
    entity_id: str
    observed_at: datetime
    stance_score: float
    sentiment_score: float
    summary: str
    aspect: str | None = None
    evidence_text: str | None = None
    confidence_score: float = 0.5


@dataclass(slots=True)
class OpinionShift:
    entity_id: str
    from_time: datetime
    to_time: datetime
    before_score: float
    after_score: float
    delta: float
    before_summary: str
    after_summary: str
    evidence_memory_ids: list[str]
    possible_causes: list[str] = field(default_factory=list)
    confidence_score: float = 0.5
    memory_id: str | None = None


@dataclass(slots=True)
class ReflectionFinding:
    finding_type: str
    evidence_memory_ids: list[str]
    summary: str
    confidence_score: float
    suggested_action: str
    changes: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
