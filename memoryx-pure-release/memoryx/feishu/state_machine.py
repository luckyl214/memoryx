"""Feishu 可见状态机 — 防止状态倒退和非法转换。

乔布斯标准：用户看到的状态必须合理，不能出现 "done → running" 或 "error → done"。

NOTE: VisibleState 和 STATE_VIEW 从 schemas 导入，避免重复定义导致 isinstance 失败。
"""
from __future__ import annotations

from .schemas import STATE_VIEW, VisibleState


# 允许的状态转换
ALLOWED_TRANSITIONS = {
    VisibleState.RECEIVED: {VisibleState.QUEUED, VisibleState.ERROR},
    VisibleState.QUEUED: {VisibleState.THINKING, VisibleState.ERROR},
    VisibleState.THINKING: {VisibleState.USING_TOOLS, VisibleState.WRITING, VisibleState.ERROR},
    VisibleState.USING_TOOLS: {VisibleState.THINKING, VisibleState.WAITING_USER, VisibleState.WRITING, VisibleState.ERROR},
    VisibleState.WAITING_USER: {VisibleState.USING_TOOLS, VisibleState.ERROR},
    VisibleState.WRITING: {VisibleState.DONE, VisibleState.DEGRADED, VisibleState.ERROR},
    VisibleState.DONE: set(),
    VisibleState.DEGRADED: set(),
    VisibleState.ERROR: set(),
}


def can_transition(old: VisibleState, new: VisibleState) -> bool:
    """检查状态转换是否合法"""
    if not isinstance(old, VisibleState) or not isinstance(new, VisibleState):
        return False
    if old == new:
        return True
    allowed = ALLOWED_TRANSITIONS.get(old, set())
    return new in allowed


def assert_transition(old: VisibleState, new: VisibleState) -> None:
    """断言状态转换合法，非法则抛出异常"""
    if not can_transition(old, new):
        raise ValueError(
            f"Invalid Feishu state transition: {old.value} -> {new.value}. "
            f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS.get(old, set())] or ['terminal']}"
        )


def get_state_display(state: VisibleState) -> tuple[str, str, str]:
    """获取状态显示信息 (emoji, text, color)"""
    return STATE_VIEW.get(state, ("❓", "未知", "grey"))
