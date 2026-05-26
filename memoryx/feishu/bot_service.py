"""飞书 → Hermes → 卡片更新服务（P14.4.3 硬化版）。

P14.4.3 集成：
  - 卡片所有权：send_interactive_card 返回 message_id 并持久化
  - 强制约束：card_message_id 为空时拒绝 mark_done
  - 卡片更新：patch_interactive_card 使用 PATCH /messages/{message_id}
  - JSON 2.0：所有卡片输出 schema="2.0", config.update_multi=true
  - 最终视图：final_view=True 只显示结果、耗时、执行摘要
  - 内部工具：execute_code/sqlite3 等调试输出不进飞书
"""
from __future__ import annotations

import asyncio
import json
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
        """接受飞书事件，先发卡片（捕获 card_message_id），确认卡片所有权后再入队。"""
        job.update_visible_state("received")

        # 记录追踪：事件已接受
        if self.trace_store:
            self.trace_store.record(
                job_id=job.job_id,
                trace_id=job.trace_id,
                phase="received",
                event_type="event_accepted",
                payload={"chat_id": job.chat_id, "message_id": job.message_id},
            )

        # P14.4.3: 先发卡片，拿到 card_message_id 再入队
        # 防止 claim_next 并发读取 payload_json 时 card_message_id=null
        card = self.renderer.render(job, final_view=False)

        try:
            result = await self.client.send_interactive_card(
                chat_id=job.chat_id,
                card=card,
            )
            job.card_message_id = result["message_id"]

            # 卡片所有权断言
            assert job.card_message_id, "send_interactive_card returned empty message_id"

            # 记录卡片发送到 feishu_card_messages 表
            self.queue.record_card_message(
                job_id=job.job_id,
                inbound_message_id=job.message_id,
                outbound_card_message_id=job.card_message_id,
                chat_id=job.chat_id,
            )

            # 追踪：卡片发送成功
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="received",
                    event_type="card_initial_sent",
                    payload={"card_message_id": job.card_message_id, "revision": job.revision},
                )
        except Exception as exc:
            # 卡片发送失败：不入队，HTTP handler 返回 500
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="received",
                    event_type="card_send_failed",
                    payload={"error": str(exc)},
                )
            raise

        # P14.4.3: 卡片已发送 → card_message_id 已就位 → 入队
        # 此时 claim_next 读取的 payload_json 已包含 card_message_id
        self.queue.enqueue(job)

        return job.job_id

    async def run_worker_once(
        self,
        runner: HermesRunner,
        *,
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None = None,
    ) -> bool:
        """领取一个 job 并处理（P14.4.3 硬化版）。"""
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

        # P14.4.3: 启动时兜底同步 card_message_id（防止 payload_json 落后）
        job = self.queue.attach_card_message_id(job)

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

        # P14.4.3: 使用 job_holder 闭包确保 callback 永远拿到最新 job
        job_holder = {"job": job}

        # P14.4.3: on_stage — 阶段变化时动态更新卡片
        async def _on_stage(stage: RunnerStage, stage_label: str) -> None:
            current = job_holder["job"]
            current.update_visible_state(stage.value)
            self.queue.update(current)
            if self.trace_store:
                self.trace_store.record(
                    job_id=current.job_id,
                    trace_id=current.trace_id,
                    phase=stage.value,
                    event_type="state_transition",
                    payload={"stage": stage.value, "revision": current.revision},
                )
            # 每次阶段变化更新卡片（不在 live_view 时跳过）
            await self._update_card(current, final_view=False)

        async def on_delta(delta: str) -> None:
            current = job_holder["job"]
            current.answer += delta

        async def on_tool(tool: ToolCallRecord) -> None:
            current = job_holder["job"]
            current.tools.append(tool)

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

            # P14.4.3: shadow runner 60s 超时，超时后生成 degraded final_view
            # 飞书事件侧要求 3 秒内 ACK，耗时操作异步处理；卡片更新也应保持"先给出状态再处理"
            shadow_timeout = float(os.getenv("FEISHU_SHADOW_RUNNER_TIMEOUT", "60"))

            # P14.4.3: 使用 on_stage 回调让阶段变化更新卡片
            if isinstance(runner, RealHermesRunner):
                final_answer = await asyncio.wait_for(
                    runner.run(job_holder["job"], on_delta, on_tool, _on_stage),
                    timeout=shadow_timeout,
                )
            else:
                # 兼容旧式 runner
                final_answer = await asyncio.wait_for(
                    runner(job_holder["job"], on_delta, on_tool),
                    timeout=shadow_timeout,
                )

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

            # P14.4.3: 更新卡片到最终视图（使用 patch_interactive_card）
            await self._update_card(job, final_view=True)

            # 追踪：job 完成前更新卡片
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="finalize",
                    event_type="card_final_patch",
                    payload={"card_message_id": job.card_message_id, "revision": job.revision},
                )

            # P14.4.3: mark_done 强制要求 card_message_id 非空
            self.queue.mark_done(job)

            # 追踪：job 完成
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="done",
                    event_type="job_done",
                    payload={
                        "card_message_id": job.card_message_id,
                        "answer_length": len(job.answer),
                        "revision": job.revision,
                    },
                )

        except asyncio.TimeoutError:
            # P14.4.3: shadow runner 超时 → degraded final_view
            job.error = f"Shadow runner timed out after {shadow_timeout}s"
            job.state = HermesRunState.ERROR
            job.visible_state = VisibleState.DEGRADED
            job.phase = "timeout"
            job.ended_at = job.ended_at or time.time()
            job.updated_at = time.time()

            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="timeout",
                    event_type="shadow_runner_timeout",
                    payload={"timeout_seconds": shadow_timeout},
                )

            # 即使超时也要更新卡片
            try:
                await self._update_card(job, final_view=True)
            except Exception:
                pass

            if job.card_message_id:
                self.queue.update(job)
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="done",
                        event_type="job_done_degraded",
                        payload={"card_message_id": job.card_message_id, "reason": "timeout"},
                    )
            else:
                self._move_to_dlq(job, "shadow_runner_timeout_no_card")

        except Exception as exc:
            job.error = str(exc)

            # 即使失败也要更新卡片
            try:
                await self._update_card(job, final_view=True)
            except Exception:
                pass

            # P14.4.3: error 状态也需要 card_message_id 才能标记
            if job.card_message_id:
                job.state = HermesRunState.ERROR
                job.visible_state = VisibleState.ERROR
                job.phase = "error"
                job.ended_at = job.ended_at or time.time()
                job.updated_at = time.time()
                self.queue.update(job)

                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="error",
                        event_type="job_error",
                        payload={
                            "card_message_id": job.card_message_id,
                            "error": str(exc)[:1000],
                        },
                    )
            else:
                # 没有 card_message_id 时，直接移入 DLQ
                if self.trace_store:
                    self.trace_store.record(
                        job_id=job.job_id,
                        trace_id=job.trace_id,
                        phase="error",
                        event_type="job_error_no_card",
                        payload={"error": str(exc)[:1000]},
                    )

                self._move_to_dlq(job, "card_message_id_empty_on_error")

        finally:
            self.queue.release_lock(job.job_id)

        return True

    def _move_to_dlq(self, job: FeishuRenderJob, reason: str) -> None:
        """将 job 移入死信队列（DLQ）"""
        with self.queue._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO feishu_dead_letters(
                    job_id, payload_json, reason, attempts, last_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    job.job_id,
                    job.to_json(),
                    reason,
                    job.attempts,
                    job.error[:1000] if job.error else "",
                    time.time(),
                ),
            )
            conn.execute("DELETE FROM feishu_jobs WHERE job_id=?;", (job.job_id,))

    async def _update_card(self, job: FeishuRenderJob, *, final_view: bool = False) -> None:
        """更新飞书卡片（P14.4.3 硬化版）。

        P14.4.3 强制校验：
        1. 每次 card patch 前必须 attach_card_message_id 兜底
        2. card_message_id 为空时 raise RuntimeError（不再 silent skip）
        """
        # P14.4.3 不变量：patch 前强制同步 card_message_id
        job = self.queue.attach_card_message_id(job)

        if not job.card_message_id:
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="card_update",
                    event_type="card_patch_refused",
                    payload={
                        "reason": "missing_card_message_id_after_reload",
                        "revision": job.revision,
                    },
                )
            raise RuntimeError(
                f"cannot patch Feishu card: job={job.job_id} has empty card_message_id "
                f"even after attach_card_message_id reload"
            )

        card = self.renderer.render(job, final_view=final_view)

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
                    payload={
                        "card_message_id": job.card_message_id,
                        "revision": job.revision,
                        "final_view": final_view,
                    },
                )
        else:
            # revision 过旧或内容相同，跳过
            if self.trace_store:
                self.trace_store.record(
                    job_id=job.job_id,
                    trace_id=job.trace_id,
                    phase="card_update",
                    event_type="card_patch_skipped",
                    payload={"reason": "revision conflict or content unchanged"},
                )

    async def _do_patch(self, message_id: str, card: dict, job: FeishuRenderJob | None = None) -> None:
        """实际发送卡片 patch — 使用 PATCH /messages/{message_id}。"""
        try:
            await self.client.patch_interactive_card(
                card_message_id=message_id,
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
