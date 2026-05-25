"""统一状态转换入口 — 所有 visible_state 变化必须走这里。

P14.4.1 UX Reliability Hotfix:
- 所有状态变化统一调用 transition_job()
- 自动校验 assert_transition
- 自动 revision +1
- 自动 trace 记录 state_transition
- 禁止零散改 visible_state / revision
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from .state_machine import VisibleState, assert_transition

if TYPE_CHECKING:
    from .queue import FeishuSQLiteQueue
    from .trace import FeishuTraceStore
    from .schemas import FeishuRenderJob


def transition_job(
    queue: "FeishuSQLiteQueue",
    trace: "FeishuTraceStore | None",
    job: "FeishuRenderJob",
    *,
    state: str,
    visible_state: str,
    reason: str,
) -> None:
    """统一状态转换：校验 → 同步对象 → 更新 DB → 记录 trace

    Args:
        queue: 队列实例
        trace: trace store 实例（可为 None）
        job: 当前 job 对象（会被原地修改）
        state: 新内部状态（如 running / done / error）
        visible_state: 新用户可见状态（如 thinking / done / error）
        reason: 转换原因（用于 trace）

    Raises:
        ValueError: 如果 assert_transition 失败
    """
    old_visible = VisibleState(job.visible_state or job.state or "received")
    new_visible = VisibleState(visible_state)

    # 1. 校验状态转换
    assert_transition(old_visible, new_visible)

    now = time.time()

    # 2. 同步 job 对象
    job.state = state
    job.visible_state = visible_state
    job.revision += 1
    job.updated_at = now

    # 3. 更新 DB payload
    payload_dict = job.to_dict()
    payload_dict["state"] = state
    payload_dict["visible_state"] = visible_state
    payload_dict["revision"] = job.revision
    payload_dict["updated_at"] = now

    queue.update(job)

    # 4. 记录 trace
    if trace:
        trace.record(
            job_id=job.job_id,
            trace_id=job.trace_id,
            phase="state",
            event_type="state_transition",
            payload={
                "from": str(old_visible),
                "to": str(new_visible),
                "state": state,
                "reason": reason,
                "revision": job.revision,
            },
        )