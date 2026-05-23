"""P6: REST API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    content: str
    memory_type: str = "FACT"
    importance_score: float = 0.5
    confidence_score: float = 0.5
    session_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    importance_score: Optional[float] = None
    confidence_score: Optional[float] = None
    active_state: Optional[str] = None


class MemoryResponse(BaseModel):
    id: str
    memory_type: str
    content: str
    importance_score: float
    confidence_score: float
    active_state: str
    created_at: str
    updated_at: str


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    tag_filter: Optional[list[str]] = None


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]
    total: int


class FeedbackRequest(BaseModel):
    memory_id: str
    positive: bool


class SelfEditPreviewRequest(BaseModel):
    memory_id: str
    edit_type: str
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class SelfEditApplyRequest(BaseModel):
    memory_id: str
    edit_type: str
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ConsolidationRequest(BaseModel):
    limit: int = 100
    dry_run: bool = True
