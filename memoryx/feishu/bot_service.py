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

import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from .client import FeishuClient
from .queue import FeishuSQLiteQueue
from .renderer import FeishuCardRenderer
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

        try:
            resp = await self.client.send_message(
                receive_id=job.chat_id,
                receive_id_type=job.receive_id_type,
                msg_type="interactive",
                content=card,
                uuid=job.job_id,
            )

            job.card_message_id = resp["data"]["message_id"]
            self.queue.update(job)
            # 追踪：卡片发送成功
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="received",
                    event_type="card_sent",
                    payload={"card_message_id": job.card_message_id},
                )
        except Exception as exc:
            # 卡片发送失败不阻断入队，但记录错误
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

    async def run_worker_once(
        self,
        runner: HermesRunner,
        *,
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None = None,
    ) -> bool:
        """领取一个 job 并处理（P14.3 增强版）"""
        # 救回卡住的 stale job
        rescued = self.queue.rescue_stale_jobs(stale_after_seconds=120, max_attempts=3)
        if rescued:
            pass  # rescued 数量可用于日志

        job = self.queue.claim_next()
        if not job:
            return False

        # 记录追踪（claim_next 已设 state=RUNNING, visible_state=THINKING）
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
            # 追踪：runner 开始
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="runner",
                    event_type="runner_start",
                    payload={"runner_type": type(runner).__name__},
                )

            # 使用真实 Hermes Runner
            if isinstance(runner, RealHermesRunner):
                final_answer = await runner.run(job, on_delta, on_tool, on_stage)
            else:
                # 兼容旧式 runner
                final_answer = await runner(job, on_delta, on_tool)

            if final_answer:
                job.answer = final_answer

            # 追踪：runner 完成
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="runner",
                    event_type="runner_done",
                    payload={"runner_type": type(runner).__name__, "answer_length": len(final_answer or "")},
                )

            # P14.4: 溢出处理 — 真正写文件并上传，不说谎
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

            # 业务成功：通过 transition_job 同步到 DB
            transition_job(
                self.queue, self.trace_store, job,
                state="done", visible_state="done",
                reason="runner_completed",
            )

        except Exception as exc:
            job.error = str(exc)
            transition_job(
                self.queue, self.trace_store, job,
                state="error", visible_state="error",
                reason="worker_exception",
            )

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
            self.queue.release_lock(job.job_id)
            self.queue.update(job)

            # 追踪：job 完成
            if self.trace_store and job.state == HermesRunState.DONE:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="done",
                    event_type="job_done",
                    payload={"answer_length": len(job.answer)},
                )

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
            sender=lambda msg_id, c: self._do_patch(msg_id, c, job=job),
        )

        if sent:
            # 追踪：卡片更新成功
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="card_update",
                    event_type="card_patch_done",
                    payload={"revision": job.revision},
                )
        else:
            # revision 过旧或内容相同，跳过
            pass

    async def _do_patch(self, message_id: str, card: dict, job: FeishuRenderJob | None = None) -> None:
        """实际发送卡片 patch — patch 失败只记 trace，不阻断 job。"""
        try:
            await self.client.patch_message_card(
                message_id=message_id,
                card=card,
            )
        except Exception as exc:
            if self.trace_store and job:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="card_update",
                    event_type="card_patch_failed",
                    payload={
                        "card_message_id": message_id,
                        "revision": job.revision,
                        "error": str(exc)[:1000],
                    },
                )
