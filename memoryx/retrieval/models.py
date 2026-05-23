from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RetrievalIntent(StrEnum):
    CODING = "coding"
    PLANNING = "planning"
    PREFERENCE = "preference"
    EMOTIONAL = "emotional"
    PROJECT = "project"
    TROUBLESHOOTING = "troubleshooting"
    WORKFLOW = "workflow"
    DEBUGGING = "debugging"
    DEPLOYMENT = "deployment"


@dataclass(slots=True)
class RetrievalResult:
    memory_id: str
    content: str
    memory_type: str
    scope: str
    semantic_score: float
    keyword_score: float
    temporal_score: float
    entity_score: float
    importance_score: float
    episodic_score: float
    final_score: float
    explanation: str
