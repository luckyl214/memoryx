"""P14.3 增强版 schemas — 添加 revision、visible_state、phase 等。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4
import json


# ── 内部运行状态（技术状态） ──
class HermesRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# ── 用户可见状态（产品状态） ──
class VisibleState(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    THINKING = "thinking"
    GENERATING = "generating"
    VERIFYING = "verifying"
    USING_TOOLS = "using_tools"
    WAITING_USER = "waiting_user"
    WRITING = "writing"
    DONE = "done"
    DEGRADED = "degraded"
    ERROR = "error"


STATE_VIEW = {
    VisibleState.RECEIVED: ("📥", "已收到", "blue"),
    VisibleState.QUEUED: ("⏳", "排队中", "blue"),
    VisibleState.THINKING: ("🧠", "正在处理", "blue"),
    VisibleState.GENERATING: ("✍️", "生成中", "blue"),
    VisibleState.VERIFYING: ("🛡️", "校验中", "yellow"),
    VisibleState.USING_TOOLS: ("🛠️", "调用工具中", "blue"),
    VisibleState.WAITING_USER: ("🟡", "等待确认", "yellow"),
    VisibleState.WRITING: ("✍️", "整理答案中", "blue"),
    VisibleState.DONE: ("✅", "已完成", "green"),
    VisibleState.DEGRADED: ("🟠", "降级完成", "yellow"),
    VisibleState.ERROR: ("🔴", "失败", "red"),
}


def get_visible_state(internal_state: HermesRunState, phase: str = "") -> VisibleState:
    """将内部状态映射为用户可见状态"""
    if internal_state == HermesRunState.ERROR:
        return VisibleState.ERROR
    if internal_state == HermesRunState.DONE:
        return VisibleState.DONE
    if internal_state == HermesRunState.QUEUED:
        return VisibleState.QUEUED

    # 根据 phase 细化 running 状态
    if phase:
        phase_to_visible = {
            "prepare": VisibleState.THINKING,
            "context": VisibleState.THINKING,
            "retrieval": VisibleState.THINKING,
            "generate": VisibleState.GENERATING,
            "tool": VisibleState.USING_TOOLS,
            "guard": VisibleState.THINKING,
            "verify": VisibleState.VERIFYING,
            "reflect": VisibleState.VERIFYING,
            "write": VisibleState.WRITING,
        }
        return phase_to_visible.get(phase, VisibleState.THINKING)

    return VisibleState.THINKING


# ── 工具调用阶段 ──
class ToolPhase(StrEnum):
    CONTEXT = "context"
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    GUARD = "guard"
    REFLECTION = "reflection"


# ── AttachmentRef 增强 ──
@dataclass(slots=True)
class AttachmentRef:
    """飞书附件引用（P14.3 增强版）"""
    kind: str  # image | file | media | audio | unknown
    file_key: str | None = None
    image_key: str | None = None
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    local_path: str | None = None
    sha256: str | None = None
    source_message_id: str | None = None
    status: str = "pending"  # pending | downloaded | parsed | failed | too_large
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AttachmentRef":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── ToolCallRecord 增强（时间线版） ──
@dataclass(slots=True)
class ToolCallRecord:
    """工具调用记录（P14.3 时间线版）"""
    id: str = ""
    name: str = ""
    phase: str = ToolPhase.TOOL  # context | retrieval | tool | guard | reflection
    status: str = "running"  # running | done | error | skipped
    user_visible_name: str = ""
    summary: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    input_preview: str = ""
    output_preview: str = ""
    guard_decision: str | None = None
    severity: str = "info"  # info | warn | danger
    collapsible: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid4())[:8]
        if not self.user_visible_name:
            self.user_visible_name = self.name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── FeishuRenderJob 增强（revision + visible_state） ──
@dataclass(slots=True)
class FeishuRenderJob:
    """飞书渲染任务（P14.3 增强版）"""
    chat_id: str
    user_id: str | None
    message_id: str | None
    text: str
    receive_id_type: str = "chat_id"

    job_id: str = field(default_factory=lambda: uuid4().hex)
    trace_id: str = field(default_factory=lambda: str(uuid4())[:12])

    # 内部状态
    state: HermesRunState = HermesRunState.QUEUED
    # 用户可见状态
    visible_state: VisibleState = VisibleState.RECEIVED
    # 当前处理阶段
    phase: str = "received"

    # revision 防乱序
    revision: int = 0

    title: str = "Hermes Agent"
    context_summary: str = ""
    answer: str = ""
    error: str = ""

    attachments: list[AttachmentRef] = field(default_factory=list)
    tools: list[ToolCallRecord] = field(default_factory=list)
    memoryx_badges: list[str] = field(default_factory=list)

    card_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Queue fields
    priority: int = 100
    attempts: int = 0
    locked_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """统一序列化 — 所有字段显式列出，确保 card_message_id 永远同步。"""
        return {
            "job_id": self.job_id,
            "trace_id": self.trace_id,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "message_id": self.message_id,
            "card_message_id": self.card_message_id,
            "state": str(self.state),
            "visible_state": str(self.visible_state),
            "phase": self.phase,
            "revision": self.revision,
            "title": self.title,
            "context_summary": self.context_summary,
            "answer": self.answer,
            "error": self.error,
            "attachments": [a.to_dict() for a in self.attachments],
            "tools": [t.to_dict() for t in self.tools],
            "memoryx_badges": self.memoryx_badges,
            "metadata": self.metadata,
            "priority": self.priority,
            "attempts": self.attempts,
            "locked_at": self.locked_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "stream_preview": getattr(self, "stream_preview", ""),
            "phase_marks": getattr(self, "phase_marks", []),
        }

    def to_json(self) -> str:
        """统一 JSON 序列化 — 用于 payload_json 写入。"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeishuRenderJob":
        data = dict(data)
        data["state"] = HermesRunState(data.get("state", HermesRunState.QUEUED))
        data["visible_state"] = VisibleState(data.get("visible_state", VisibleState.RECEIVED))
        data["attachments"] = [AttachmentRef.from_dict(x) if isinstance(x, dict) else x for x in data.get("attachments", [])]
        data["tools"] = [ToolCallRecord.from_dict(x) if isinstance(x, dict) else x for x in data.get("tools", [])]
        return cls(**data)

    def update_visible_state(self, phase: str = "") -> None:
        """根据内部状态和 phase 更新可见状态"""
        self.visible_state = get_visible_state(self.state, phase)
        self.phase = phase
        self.revision += 1

    def next_revision(self) -> int:
        """获取下一个 revision"""
        self.revision += 1
        return self.revision

    stream_preview: str = ""
    phase_marks: list[str] = field(default_factory=list)
