from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from memoryx.retrieval import RetrievalResult


class RoutingIntent(StrEnum):
    CODING = "coding"
    PLANNING = "planning"
    EMOTIONAL = "emotional"
    PROJECT = "project"
    TROUBLESHOOTING = "troubleshooting"
    DEBUGGING = "debugging"


@dataclass(slots=True)
class RoutePlan:
    intent: RoutingIntent
    primary_route: str
    route_scores: dict[str, float] = field(default_factory=dict)
    results: list[RetrievalResult] = field(default_factory=list)
