from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EmbeddingRequest:
    memory_id: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddingResult:
    memory_id: str
    vector: list[float]
    dimension: int
    freshness_score: float
    metadata: dict[str, str] = field(default_factory=dict)
