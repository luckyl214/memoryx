from __future__ import annotations

from dataclasses import dataclass, field

from memoryx.extraction import ExtractionMemory


@dataclass(slots=True)
class QuarantineReport:
    should_quarantine: bool
    score: float
    flags: list[str] = field(default_factory=list)


class QuarantineManager:
    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold

    def is_prompt_injection(self, content: str) -> bool:
        lowered = content.lower()
        indicators = (
            "ignore previous instructions",
            "ignore system instructions",
            "exfiltrate",
            "root password",
            "api key",
            "system prompt",
            "developer message",
            "override instructions",
        )
        return any(indicator in lowered for indicator in indicators)

    def inspect(self, memory: ExtractionMemory) -> QuarantineReport:
        flags: list[str] = []
        score = 0.0
        if self.is_prompt_injection(memory.content):
            flags.append("prompt injection pattern detected")
            score += 0.75
        if memory.confidence_score > 0.85 and memory.importance_score > 0.85 and len(memory.content) > 80:
            score += 0.1
        if any(word in memory.content.lower() for word in ("secret", "password", "token", "key")):
            flags.append("sensitive secret-like content")
            score += 0.25
        should_quarantine = score >= self.threshold
        return QuarantineReport(should_quarantine=should_quarantine, score=min(1.0, score), flags=flags)
