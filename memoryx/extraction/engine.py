from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol

from .models import ExtractionMemory, ExtractionRequest, ExtractionResult, ExtractionSource


class ExtractionClient(Protocol):
    async def extract(self, request: ExtractionRequest) -> dict: ...


class MemoryExtractionEngine:
    def __init__(self, client: ExtractionClient, batch_size: int = 8, min_importance: float = 0.3, min_confidence: float = 0.4) -> None:
        self.client = client
        self.batch_size = batch_size
        self.min_importance = min_importance
        self.min_confidence = min_confidence

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        all_memories: list[ExtractionMemory] = []
        for batch in self._batched(request.sources):
            payload = await self.client.extract(ExtractionRequest(session_id=request.session_id, sources=batch))
            all_memories.extend(self._normalize_payload(payload))
        filtered = [
            memory
            for memory in all_memories
            if memory.importance_score >= self.min_importance and memory.confidence_score >= self.min_confidence
        ]
        return ExtractionResult(memories=filtered)

    def _batched(self, sources: list[ExtractionSource]) -> Iterable[list[ExtractionSource]]:
        for index in range(0, len(sources), self.batch_size):
            yield sources[index : index + self.batch_size]

    def _normalize_payload(self, payload: dict) -> list[ExtractionMemory]:
        result: list[ExtractionMemory] = []
        for item in payload.get("memories", []):
            if "timestamp" not in item or not item["timestamp"]:
                item = {**item, "timestamp": datetime.now(timezone.utc).isoformat()}
            result.append(ExtractionMemory.model_validate(item))
        return result
