# memoryx/feishu/bot_service.py
"""
飞书 → Hermes → 卡片更新服务。

流程：
  1. 接受飞书事件 → 创建 job 入队
  2. 发送排队中卡片
  3. worker 领取 job → 更新为处理中卡片
  4. 调用 Hermes runner → stream 节流更新卡片
  5. 完成后更新为已完成卡片
  6. MemoryX 保存对话、附件、工具轨迹、反思
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from .client import FeishuClient
from .queue import FeishuSQLiteQueue
from .renderer import FeishuCardRenderer
from .schemas import FeishuRenderJob, HermesRunState, ToolCallRecord


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
    ) -> None:
        self.client = client
        self.queue = queue
        self.renderer = renderer or FeishuCardRenderer()
        self.update_interval_seconds = update_interval_seconds

    async def accept_event(self, job: FeishuRenderJob) -> str:
        """接受飞书事件，创建排队中卡片"""
        self.queue.enqueue(job)

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

    async def run_worker_once(self, runner: HermesRunner) -> bool:
        """领取一个 job 并处理"""
        job = self.queue.claim_next()
        if not job:
            return False

        job.state = HermesRunState.RUNNING
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
            final_answer = await runner(job, on_delta, on_tool)
            if final_answer:
                job.answer = final_answer
            job.state = HermesRunState.DONE
        except Exception as exc:
            job.state = HermesRunState.ERROR
            job.error = str(exc)
        finally:
            await self._update_card(job)
            self.queue.update(job)

        return True

    async def _update_card(self, job: FeishuRenderJob) -> None:
        """更新飞书卡片（失败不阻断）"""
        if not job.card_message_id:
            return

        card = self.renderer.render(job)
        try:
            await self.client.patch_message_card(
                message_id=job.card_message_id,
                card=card,
            )
        except Exception:
            pass  # 卡片更新失败不能导致 job 丢失
