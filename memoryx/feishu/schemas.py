# memoryx/feishu/schemas.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class HermesRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass(slots=True)
class AttachmentRef:
    """飞书附件引用"""
    kind: str  # image | file | media | audio | unknown
    file_key: str | None = None
    image_key: str | None = None
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    local_path: str | None = None
    source_message_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCallRecord:
    """工具调用记录"""
    name: str
    status: str = "running"  # running | done | error | skipped
    summary: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    input_preview: str = ""
    output_preview: str = ""
    guard_decision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FeishuRenderJob:
    """飞书渲染任务"""
    chat_id: str
    user_id: str | None
    message_id: str | None
    text: str
    receive_id_type: str = "chat_id"

    job_id: str = field(default_factory=lambda: uuid4().hex)
    state: HermesRunState = HermesRunState.QUEUED

    title: str = "Hermes Agent"
    trace_id: str | None = None
    context_summary: str = ""
    answer: str = ""
    error: str = ""

    attachments: list[AttachmentRef] = field(default_factory=list)
    tools: list[ToolCallRecord] = field(default_factory=list)
    memoryx_badges: list[str] = field(default_factory=list)

    card_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Queue fields (not used in rendering, only for persistence)
    priority: int = 100
    attempts: int = 0
    locked_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = str(self.state)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeishuRenderJob":
        data = dict(data)
        data["state"] = HermesRunState(data.get("state", HermesRunState.QUEUED))
        data["attachments"] = [AttachmentRef(**x) for x in data.get("attachments", [])]
        data["tools"] = [ToolCallRecord(**x) for x in data.get("tools", [])]
        return cls(**data)
