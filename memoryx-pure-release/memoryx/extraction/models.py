from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceKind = Literal["user_message", "assistant_response", "tool_output", "tool_result", "tool_call"]


class ExtractionSource(BaseModel):
    kind: SourceKind
    content: str = Field(min_length=1)
    source_message_id: str | None = None
    tool_name: str | None = None


class ExtractionRequest(BaseModel):
    session_id: str
    sources: list[ExtractionSource] = Field(default_factory=list)


class ExtractionMemory(BaseModel):
    memory_type: str
    content: str
    importance_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    scope: str = "global"
    timestamp: datetime
    source_message_id: str | None = None
    reasoning: str = ""


class ExtractionResult(BaseModel):
    memories: list[ExtractionMemory] = Field(default_factory=list)
