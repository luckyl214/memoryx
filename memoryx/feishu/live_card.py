"""飞书 Live Card 控制器 — 唯一状态更新 + 卡片 patch 入口。

P14.4.2 Feishu Single-Card Live UX Hotfix:
- transition_and_patch() 是所有状态更新和卡片更新的唯一入口
- 每次状态变化都强制 patch 同一张卡片
- final_view=True 时隐藏过程信息，只显示最终结果
- 所有时间展示使用 Asia/Shanghai / CST
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from .state_machine import VisibleState, assert_transition


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_cst_iso() -> str:
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


def format_cst(ts: float | int | str | None) -> str:
    """格式化时间戳为 CST/北京时间字符串"""
    if ts is None:
        return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S CST")

    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S CST")

    text = str(ts)
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
        return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S CST")
    except Exception:
        return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S CST")


STATE_LABEL = {
    VisibleState.RECEIVED: ("📥", "已收到"),
    VisibleState.QUEUED: ("⏳", "排队中"),
    VisibleState.THINKING: ("🧠", "正在处理"),
    VisibleState.USING_TOOLS: ("🛠️", "调用工具中"),
    VisibleState.WAITING_USER: ("🟡", "等待确认"),
    VisibleState.WRITING: ("✍️", "整理结果"),
    VisibleState.DONE: ("✅", "已完成"),
    VisibleState.DEGRADED: ("🟠", "降级完成"),
    VisibleState.ERROR: ("🔴", "失败"),
}


@dataclass(slots=True)
class LiveCardPatchResult:
    patched: bool
    revision: int
    visible_state: str
    card_message_id: str = ""


class FeishuLiveCardController:
    """Single source of truth for Feishu card state + rendering + patching.

    Contract:
    - Every visible state transition goes through transition_and_patch().
    - Every patch uses card_message_id, never inbound user message_id.
    - Final patch hides transient process details.
    """

    def __init__(
        self,
        *,
        queue: Any,
        renderer: Any,
        client: Any,
        trace: Any,
        coalescer: Any,
    ) -> None:
        self.queue = queue
        self.renderer = renderer
        self.client = client
        self.trace = trace
        self.coalescer = coalescer

    async def transition_and_patch(
        self,
        job: Any,
        *,
        state: str,
        visible_state: str,
        phase: str,
        reason: str,
        patch: bool = True,
        final_view: bool = False,
    ) -> LiveCardPatchResult:
        """状态转换 + DB 更新 + 卡片 patch 的原子操作"""
        old_visible = VisibleState(job.visible_state or job.state)
        new_visible = VisibleState(visible_state)
        assert_transition(old_visible, new_visible)

        now = time.time()
        job.state = state
        job.visible_state = visible_state
        job.phase = phase
        job.updated_at = now
        job.revision = int(getattr(job, "revision", 0) or 0) + 1
        job.updated_at_display = format_cst(now)

        # DB update with optimistic concurrency
        ok = self.queue.update(
            job.job_id,
            {
                "state": job.state,
                "visible_state": job.visible_state,
                "phase": job.phase,
                "revision": job.revision,
                "updated_at": now,
                "payload_json": self._job_to_json(job),
            },
            expected_revision=job.revision - 1,
        )

        if not ok:
            raise RuntimeError(
                f"stale revision update refused for job={job.job_id} rev={job.revision}"
            )

        self.trace.record(
            job_id=job.job_id,
            trace_id=job.trace_id,
            phase="state",
            event_type="state_transition",
            payload={
                "from": str(old_visible),
                "to": str(new_visible),
                "state": state,
                "phase": phase,
                "reason": reason,
                "revision": job.revision,
                "time_cst": job.updated_at_display,
            },
        )

        if patch:
            await self._patch_card(job, reason=reason, final_view=final_view)

        return LiveCardPatchResult(
            patched=patch,
            revision=job.revision,
            visible_state=visible_state,
            card_message_id=job.card_message_id or "",
        )

    async def _patch_card(self, job: Any, *, reason: str, final_view: bool = False) -> None:
        """执行卡片 patch，统一使用 card_message_id"""
        if not job.card_message_id:
            raise RuntimeError(
                f"job={job.job_id} has no card_message_id; cannot patch card"
            )

        card = self.renderer.render(job, final_view=final_view)

        # Shared card update requires update_multi=true
        card.setdefault("config", {})
        card["config"]["update_multi"] = True

        try:
            patched = await self.coalescer.patch(
                message_id=job.card_message_id,
                card=card,
                revision=job.revision,
                sender=self.client.patch_message_card,
            )

            self.trace.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="card",
                event_type="card_patch_done" if patched else "card_patch_skipped",
                payload={
                    "card_message_id": job.card_message_id,
                    "revision": job.revision,
                    "reason": reason,
                    "final_view": final_view,
                },
            )

        except Exception as exc:
            self.trace.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="card",
                event_type="card_patch_failed",
                payload={
                    "card_message_id": job.card_message_id,
                    "revision": job.revision,
                    "reason": reason,
                    "error": str(exc)[:1000],
                },
            )
            raise

    async def patch_card(
        self,
        job: Any,
        *,
        reason: str,
        final_view: bool = False,
    ) -> None:
        """直接 patch 卡片，不改变状态（用于 stream delta 更新）。
        如果 card_message_id 为空则跳过（initial card 还未发送）。"""
        if not job.card_message_id:
            return
        await self._patch_card(job, reason=reason, final_view=final_view)

    def _job_to_json(self, job: Any) -> str:
        """序列化 job 为 JSON 字符串"""
        import json

        d: dict[str, Any] = {}
        for attr in ("job_id", "trace_id", "state", "visible_state", "phase",
                     "revision", "title", "answer", "error",
                     "card_message_id", "chat_id", "message_id",
                     "created_at", "updated_at", "started_at", "ended_at",
                     "updated_at_display"):
            v = getattr(job, attr, None)
            if v is not None:
                d[attr] = v

        for attr in ("attachments", "tool_calls", "phase_marks", "memoryx_badges"):
            v = getattr(job, attr, None)
            if v is not None:
                d[attr] = self._serialize_list(v)

        return json.dumps(d, default=str)

    def _serialize_list(self, items: list) -> list:
        """序列化列表对象为 dict"""
        result = []
        for item in items:
            if hasattr(item, "__dict__"):
                result.append(asdict(item))
            elif hasattr(item, "to_dict"):
                result.append(item.to_dict())
            elif isinstance(item, (str, int, float, bool)):
                result.append(item)
            else:
                result.append(str(item))
        return result