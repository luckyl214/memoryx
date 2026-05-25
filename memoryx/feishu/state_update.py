"""统一状态更新入口 — 所有状态变化只能走这个函数。

原则：
- 所有 state / visible_state / revision 变化统一经过 transition_job
- 禁止直接写 job.state / job.visible_state
- 每次 transition 记录 trace 事件
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .state_machine import VisibleState, assert_transition

if TYPE_CHECKING:
    from .queue import FeishuSQLiteQueue
    from .trace import FeishuTraceStore
    from .schemas import FeishuRenderJob


def transition_job(
    *,
    queue: FeishuSQLiteQueue,
    trace: FeishuTraceStore | None,
    job: FeishuRenderJob,
    state: str,
    visible_state: str,
    reason: str,
) -> None:
    """统一状态更新函数。

    检查合法性 → 更新对象 → 更新 DB → 记录 trace。

    Args:
        queue:  队列（写 DB）
        trace:  追踪存储
        job:    当前 job 对象（会被原地修改）
        state:  新内部状态 (queued|running|done|error)
        visible_state:  新可见状态 (received|queued|thinking|...|done|error)
        reason: 转换原因（记录到 trace）
    """
    from .schemas import HermesRunState, VisibleState as VS

    old_visible = VS(job.visible_state.value if hasattr(job.visible_state, 'value') else str(job.visible_state))
    new_visible = VS(visible_state)
    assert_transition(old_visible, new_visible)

    now = time.time()
    job.state = HermesRunState(state)
    job.visible_state = VS(visible_state)
    job.revision += 1
    job.updated_at = now

    queue.update(job)

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
