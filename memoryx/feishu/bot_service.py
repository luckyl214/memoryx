"""飞书 → Hermes → 卡片更新服务（P14.4.2 Single-Card Live UX）

P14.4.2 Feishu Single-Card Live UX Hotfix:
- 每个阶段都调用 live_card.transition_and_patch()
- stream delta 只更新卡片，不发文本消息
- final_view=True 时隐藏过程信息
- 内部工具信息只进 trace，不进卡片正文
"""
from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from .client import FeishuClient, FeishuSendCardResult, FeishuAPIError
from .queue import FeishuSQLiteQueue
from .renderer import FeishuCardRenderer
from .live_card import FeishuLiveCardController
from .schemas import (
    AttachmentRef,
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
    VisibleState,
    get_visible_state,
)
from .state_update import transition_job
from .state_machine import STATE_VIEW
from .update_coalescer import CardUpdateCoalescer
from .overflow import CardOverflowPolicy, OverflowResult
from .overflow_file import OverflowFileWriter
from .output_policy import FeishuOutputPolicy
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
        overflow_file_writer: OverflowFileWriter | None = None,
        output_policy: FeishuOutputPolicy | None = None,
        attachment_preparer: AttachmentPreparer | None = None,
        trace_store: FeishuTraceStore | None = None,
        coalescer: CardUpdateCoalescer | None = None,
    ) -> None:
        self.client = client
        self.queue = queue
        self.renderer = renderer or FeishuCardRenderer()
        self.update_interval_seconds = update_interval_seconds
        self.overflow_policy = overflow_policy or CardOverflowPolicy()
        self.overflow_file_writer = overflow_file_writer or OverflowFileWriter(
            spool_dir=Path(os.getenv("FEISHU_SPOOL_DIR", "./data/feishu_spool"))
        )
        self.output_policy = output_policy or FeishuOutputPolicy()
        self.attachment_preparer = attachment_preparer or AttachmentPreparer()
        self.trace_store = trace_store

        self.coalescer = coalescer or CardUpdateCoalescer(min_interval=update_interval_seconds)

        # P14.4.2: Live Card Controller — 唯一状态更新 + 卡片 patch 入口
        self.live_card = FeishuLiveCardController(
            queue=queue,
            renderer=self.renderer,
            client=client,
            trace=trace_store,
            coalescer=self.coalescer,
        )

    async def accept_event(self, job: FeishuRenderJob) -> str:
        """接受飞书事件，创建排队中卡片（P14.4.3: 必须保存 card_message_id）"""
        job.update_visible_state("received")
        self.queue.enqueue(job)

        # 追踪：job 入队
        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="queue",
                event_type="job_queued",
                payload={
                    "chat_id": job.chat_id,
                    "message_id": job.message_id,
                    "runner_mode": os.getenv("FEISHU_RUNNER_MODE", "echo"),
                },
            )

        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="received",
                event_type="event_accepted",
                payload={"chat_id": job.chat_id, "message_id": job.message_id},
            )

        # P14.4.3: 使用 send_card 发送初始卡片，保存出站 message_id
        card = self.renderer.render(job, final_view=False)
        card.setdefault("config", {})
        card["config"]["update_multi"] = True

        try:
            result = await self.client.send_card(
                chat_id=job.chat_id,
                card=card,
            )

            job.card_message_id = result.message_id
            job.revision = int(job.revision or 0) + 1
            self.queue.update(job)

            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="received",
                    event_type="card_sent",
                    payload={"card_message_id": job.card_message_id},
                )
        except Exception as exc:
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="received",
                    event_type="card_send_failed",
                    payload={"error": str(exc)},
                )
            raise

        return job.job_id

    async def ensure_initial_card(self, job) -> None:
        """P14.4.3: 确保 job 有 card_message_id。没有则发送初始卡片。"""
        if getattr(job, 'card_message_id', None):
            return

        card = self.renderer.render(job, final_view=False)
        card.setdefault("config", {})
        card["config"]["update_multi"] = True

        result = await self.client.send_card(
            chat_id=job.chat_id,
            card=card,
        )

        job.card_message_id = result.message_id
        job.revision = int(getattr(job, "revision", 0) or 0) + 1

        track = f'card_message_id={job.card_message_id} revision={job.revision}'
        self.queue.update(job)

        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="card",
                event_type="card_initial_sent",
                payload={
                    "card_message_id": job.card_message_id,
                    "revision": job.revision,
                    "chat_id": job.chat_id,
                },
            )

    async def run_worker_once(
        self,
        runner: HermesRunner,
        *,
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None = None,
    ) -> bool:
        """领取一个 job 并处理（P14.4.2 每阶段 transition_and_patch）"""
        self.queue.rescue_stale_jobs(stale_after_seconds=120, max_attempts=3)

        job = self.queue.claim_next()
        if not job:
            return False

        # P14.4.3: 确保有 card_message_id，没有则发送初始卡片
        await self.ensure_initial_card(job)

        # 追踪：job claimed
        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="worker",
                event_type="job_claimed",
                payload={"runner_mode": os.getenv("FEISHU_RUNNER_MODE", "echo")},
            )

        try:
            # ── Phase: Prepare ──
            job.started_at = time.time()
            await self.live_card.transition_and_patch(
                job,
                state="running",
                visible_state="thinking",
                phase="prepare",
                reason="worker_claimed",
                final_view=False,
            )

            # 下载附件
            job.attachments = await self.queue.download_attachments(job, self.client)

            # 附件预处理
            prepared_attachments = []
            for att in job.attachments:
                prepared = self.attachment_preparer.prepare(att)
                prepared_attachments.append(prepared)
                if not prepared.is_usable():
                    if self.trace_store:
                        self.trace_store.record(
                            job_id=job.job_id,
                            trace_id=job.trace_id,
                            phase="prepare",
                            event_type="attachment_unusable",
                            payload={"name": prepared.name, "status": prepared.status},
                        )

            await self.live_card.transition_and_patch(
                job,
                state="running",
                visible_state="thinking",
                phase="prepare",
                reason="prepare_done",
                final_view=False,
            )

            # ── Phase: Context ──
            job.phase_marks = ["prepare"]
            await self.live_card.transition_and_patch(
                job,
                state="running",
                visible_state="thinking",
                phase="context",
                reason="memoryx_context_start",
                final_view=False,
            )

            # ── Stream / Tool 回调 ──
            last_update = 0.0

            async def on_delta(delta: str) -> None:
                nonlocal last_update
                clean = self.output_policy.is_internal_noise(delta)
                if clean:
                    if self.trace_store:
                        self.trace_store.record(
                            job_id=job.job_id,
                            trace_id=job.trace_id,
                            phase="stream",
                            event_type="stream_noise_suppressed",
                            payload={"preview": delta[:200]},
                        )
                    return

                job.answer += delta
                now = time.monotonic()
                if now - last_update >= self.update_interval_seconds:
                    last_update = now
                    # stream delta 只 patch 卡片，不改状态
                    await self.live_card.patch_card(
                        job,
                        reason="stream_delta",
                        final_view=False,
                    )

            async def on_tool(tool: ToolCallRecord) -> None:
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="tool",
                        event_type=f"tool_{tool.status}",
                        payload={
                            "name": tool.name,
                            "phase": tool.phase,
                            "status": tool.status,
                            "summary": tool.summary[:500] if tool.summary else "",
                        },
                    )

                if self.output_policy.should_show_tool(tool):
                    job.tool_calls.append(tool)
                    job.phase_marks.append(tool.phase or tool.name)
                    await self.live_card.patch_card(
                        job,
                        reason="tool_update",
                        final_view=False,
                    )

            # ── Phase: Generate ──
            job.phase_marks.append("generate")
            await self.live_card.transition_and_patch(
                job,
                state="running",
                visible_state="thinking",
                phase="generate",
                reason="runner_start",
                final_view=False,
            )

            # 追踪：runner start
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="runner",
                    event_type="runner_start",
                    payload={"runner_type": type(runner).__name__},
                )
                if type(runner).__name__ in ("ShadowFeishuRunner",):
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="hermes",
                        event_type="hermes_cli_start",
                        payload={"prompt_length": len(job.text or ""), "mode": "shadow"},
                    )

            # 执行 runner
            if isinstance(runner, RealHermesRunner):
                final_answer = await runner.run(job, on_delta, on_tool, on_stage)
            else:
                final_answer = await runner(job, on_delta, on_tool)

            if final_answer:
                job.answer = final_answer

            # 追踪：runner done
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="runner",
                    event_type="runner_done",
                    payload={"runner_type": type(runner).__name__, "answer_length": len(final_answer or "")},
                )
                if type(runner).__name__ in ("ShadowFeishuRunner",):
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="hermes",
                        event_type="hermes_cli_done",
                        payload={"answer_length": len(final_answer or ""), "mode": "shadow"},
                    )

            # ── Overflow 处理 ──
            overflow = self.overflow_policy.split(job.answer)
            if overflow.overflow:
                job.answer = overflow.card_text
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="generate",
                        event_type="overflow",
                        payload={"reason": overflow.overflow_reason},
                    )
                try:
                    md_path = self.overflow_file_writer.write_markdown(
                        job_id=job.job_id,
                        title=job.title or "Hermes Answer",
                        content=overflow.overflow_text,
                    )
                    file_key = await self.client.upload_file(
                        path=str(md_path),
                        file_type="stream",
                    )
                    job.attachments.append(AttachmentRef(
                        kind="file",
                        name=md_path.name,
                        local_path=str(md_path),
                        file_key=file_key,
                        status="uploaded",
                        extra={"note": "完整回答已转为 Markdown 附件"},
                    ))
                    if self.trace_store:
                        self.trace_store.record(
                            job_id=job.job_id,
                            trace_id=job.trace_id,
                            phase="overflow",
                            event_type="overflow_file_uploaded",
                            payload={"path": str(md_path), "file_key": file_key},
                        )
                except Exception as exc:
                    job.answer = (
                        overflow.card_text
                        + "\n\n⚠️ 完整内容过长，但转附件失败。请查看系统日志或重试。"
                    )
                    if self.trace_store:
                        self.trace_store.record(
                            job_id=job.job_id,
                            trace_id=job.trace_id,
                            phase="overflow",
                            event_type="overflow_file_failed",
                            payload={"error": str(exc)[:1000]},
                        )
            else:
                job.answer = overflow.card_text

            # ── Verify / Finalize ──
            job.phase_marks.append("verify")
            await self.live_card.transition_and_patch(
                job,
                state="running",
                visible_state="writing",
                phase="verify",
                reason="claim_guard_start",
                final_view=False,
            )

            # ── Done: final view ──
            job.phase_marks.append("done")
            job.ended_at = time.time()

            await self.live_card.transition_and_patch(
                job,
                state="done",
                visible_state="done",
                phase="done",
                reason="runner_completed",
                final_view=True,
            )

            # 标记完成 — 使用 queue.update + release_lock
            self.queue.update(job)
            self.queue.release_lock(job.job_id)

            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="worker",
                    event_type="job_done",
                    payload={
                        "revision": getattr(job, "revision", 0),
                        "final_view": True,
                    },
                )

            return True

        except Exception as exc:
            job.error = str(exc)

            try:
                await self.live_card.transition_and_patch(
                    job,
                    state="error",
                    visible_state="error",
                    phase="error",
                    reason="worker_exception",
                    final_view=True,
                )
            finally:
                self.queue.update(job)
                self.queue.release_lock(job.job_id)
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="worker",
                        event_type="job_error",
                        payload={"error": str(exc)[:1000]},
                    )

            return True