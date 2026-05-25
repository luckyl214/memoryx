"""飞书 → Hermes → 卡片更新服务（P14.3 增强版）。

P14.3 集成：
  - 可见状态机（防止状态倒退）
  - 卡片更新合并器（防乱序、防闪）
  - 溢出处理（长答案转附件）
  - 附件预处理（确认 Hermes 能消费）
  - 全链路追踪
  - Hermes 真实 Runner（五阶段编排）
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from .client import FeishuClient
from .queue import FeishuSQLiteQueue
from .renderer import FeishuCardRenderer
from .schemas import (
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
    VisibleState,
    get_visible_state,
)
from .state_machine import assert_transition, STATE_VIEW
from .update_coalescer import CardUpdateCoalescer
from .overflow import CardOverflowPolicy, OverflowResult
from .attachment_prepare import AttachmentPreparer, PreparedAttachment
from .trace import FeishuTraceStore
from .hermes_runner import HermesRunner as RealHermesRunner, RunnerStage


HermesRunner = Callable[
    [
        FeishuRenderJob,
        Callable[[str], Awaitable[None]],
        Callable[[ToolCallRecord], Awaitable[None]],
    ],
    Awaitable[str],
]


class FeishuHermesBotService:
    def __init__(
        self,
        *,
        client: FeishuClient,
        queue: FeishuSQLiteQueue,
        renderer: FeishuCardRenderer | None = None,
        update_interval_seconds: float = 0.8,
        overflow_policy: CardOverflowPolicy | None = None,
        attachment_preparer: AttachmentPreparer | None = None,
        trace_store: FeishuTraceStore | None = None,
        coalescer: CardUpdateCoalescer | None = None,
    ) -> None:
        self.client = client
        self.queue = queue
        self.renderer = renderer or FeishuCardRenderer()
        self.update_interval_seconds = update_interval_seconds
        self.overflow_policy = overflow_policy or CardOverflowPolicy()
        self.attachment_preparer = attachment_preparer or AttachmentPreparer()
        self.trace_store = trace_store
        self.coalescer = coalescer or CardUpdateCoalescer(min_interval=update_interval_seconds)

    async def accept_event(self, job: FeishuRenderJob) -> str:
        """接受飞书事件，创建排队中卡片"""
        job.update_visible_state("received")
        self.queue.enqueue(job)

        # 记录追踪
        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="received",
                event_type="event_accepted",
                payload={"chat_id": job.chat_id, "message_id": job.message_id},
            )

        card = self.renderer.render(job)

        resp = await self.client.send_message(
            receive_id=job.chat_id,
            receive_id_type=job.receive_id_type,
            msg_type="interactive",
            content=card,
            uuid=job.job_id,
        )

        try:
            job.card_message_id = resp["data"]["message_id"]
            self.queue.update(job)
        except Exception:
            pass  # 卡片发送失败不阻断入队

        return job.job_id

    async def run_worker_once(
        self,
        runner: HermesRunner,
        *,
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None = None,
    ) -> bool:
        """领取一个 job 并处理（P14.3 增强版）"""
        job = self.queue.claim_next()
        if not job:
            return False

        job.state = HermesRunState.RUNNING
        job.update_visible_state("prepare")
        self.queue.update(job)

        # 记录追踪
        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="prepare",
                event_type="job_claimed",
            )

        # P14.2: 下载附件（如果有）
        job.attachments = await self.queue.download_attachments(job, self.client)
        self.queue.update(job)

        # P14.3: 附件预处理
        prepared_attachments = []
        for att in job.attachments:
            prepared = self.attachment_preparer.prepare(att)
            prepared_attachments.append(prepared)
            if not prepared.is_usable():
                # 记录不可用附件
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="prepare",
                        event_type="attachment_unusable",
                        payload={"name": prepared.name, "status": prepared.status},
                    )

        await self._update_card(job)

        last_update = 0.0

        async def on_delta(delta: str) -> None:
            nonlocal last_update
            job.answer += delta
            now = time.monotonic()
            if now - last_update >= self.update_interval_seconds:
                last_update = now
                await self._update_card(job)

        async def on_tool(tool: ToolCallRecord) -> None:
            job.tools.append(tool)
            await self._update_card(job)

        try:
            # 使用真实 Hermes Runner
            if isinstance(runner, RealHermesRunner):
                final_answer = await runner.run(job, on_delta, on_tool, on_stage)
            else:
                # 兼容旧式 runner
                final_answer = await runner(job, on_delta, on_tool)

            if final_answer:
                job.answer = final_answer

            # P14.3: 溢出处理
            overflow = self.overflow_policy.split(job.answer)
            job.answer = overflow.card_text
            if overflow.overflow and self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="generate",
                    event_type="overflow",
                    payload={"reason": overflow.overflow_reason},
                )

            job.state = HermesRunState.DONE
            job.update_visible_state("done")

        except Exception as exc:
            job.state = HermesRunState.ERROR
            job.error = str(exc)
            job.update_visible_state("error")

            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="error",
                    event_type="job_failed",
                    payload={"error": str(exc)},
                )
        finally:
            await self._update_card(job)
            self.queue.update(job)

        return True

    async def _update_card(self, job: FeishuRenderJob) -> None:
        """更新飞书卡片（P14.3: 带 revision 防乱序）"""
        if not job.card_message_id:
            return

        card = self.renderer.render(job)

        # 使用 coalescer 防乱序
        sent = await self.coalescer.patch(
            message_id=job.card_message_id,
            card=card,
            revision=job.revision,
            sender=self._do_patch,
        )

        if not sent:
            # revision 过旧或内容相同，跳过
            pass

    async def _do_patch(self, message_id: str, card: dict) -> None:
        """实际发送卡片 patch"""
        try:
            await self.client.patch_message_card(
                message_id=message_id,
                card=card,
            )
        except Exception:
            pass  # 卡片更新失败不能导致 job 丢失
