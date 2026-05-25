"""Hermes 真实 Runner — 五阶段确定性编排。

阶段：
    PREPARE → CONTEXT → GENERATE → VERIFY → REFLECT

每个阶段都产生 card event，飞书 UI 永远知道现在卡在哪一步。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable

from .schemas import (
    FeishuRenderJob,
    HermesRunState,
    ToolCallRecord,
    ToolPhase,
    VisibleState,
    get_visible_state,
)
from .state_machine import assert_transition


class RunnerStage(StrEnum):
    PREPARE = "prepare"
    CONTEXT = "context"
    GENERATE = "generate"
    VERIFY = "verify"
    REFLECT = "reflect"


@dataclass(slots=True)
class StageReport:
    """阶段执行报告"""
    stage: RunnerStage
    success: bool
    duration_ms: int
    error: str = ""
    metadata: dict[str, Any] | None = None


class HermesRunner:
    """Hermes 真实 Runner — 五阶段确定性编排。

    使用方式：
        runner = HermesRunner(
            memoryx_provider=memoryx_provider,
            hermes_client=hermes_client,
        )
        result = await runner.run(job, on_delta, on_tool)
    """

    def __init__(
        self,
        *,
        memoryx_provider: Any,  # MemoryXHermesProvider
        hermes_client: Any,     # Hermes LLM client
        max_tool_calls: int = 5,
        max_tokens: int = 4096,
    ) -> None:
        self.memoryx_provider = memoryx_provider
        self.hermes_client = hermes_client
        self.max_tool_calls = max_tool_calls
        self.max_tokens = max_tokens
        self._stage_reports: list[StageReport] = []

    async def run(
        self,
        job: FeishuRenderJob,
        on_delta: Callable[[str], Awaitable[None]],
        on_tool: Callable[[ToolCallRecord], Awaitable[None]],
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None = None,
    ) -> str:
        """运行五阶段编排。

        Args:
            job: 渲染任务
            on_delta: 接收 stream delta 的回调
            on_tool: 接收工具调用的回调
            on_stage: 接收阶段更新的回调（可选）

        Returns:
            最终答案
        """
        self._stage_reports = []
        final_answer = ""

        # ── Stage 1: PREPARE ──
        report = await self._run_stage(
            job, RunnerStage.PREPARE,
            lambda: self._stage_prepare(job),
            on_stage,
        )
        if not report.success:
            job.state = HermesRunState.ERROR
            job.error = f"PREPARE failed: {report.error}"
            return ""

        # ── Stage 2: CONTEXT (MemoryX) ──
        report = await self._run_stage(
            job, RunnerStage.CONTEXT,
            lambda: self._stage_context(job),
            on_stage,
        )
        if not report.success:
            # context 失败但非致命，继续生成
            pass

        # ── Stage 3: GENERATE (Hermes LLM) ──
        report = await self._run_stage(
            job, RunnerStage.GENERATE,
            lambda: self._stage_generate(job, on_delta, on_tool),
            on_stage,
        )
        if report.success:
            final_answer = job.answer

        # ── Stage 4: VERIFY (Claim Guard) ──
        report = await self._run_stage(
            job, RunnerStage.VERIFY,
            lambda: self._stage_verify(job),
            on_stage,
        )
        if not report.success:
            # verify 失败但非致命
            pass

        # ── Stage 5: REFLECT (Narrative) ──
        report = await self._run_stage(
            job, RunnerStage.REFLECT,
            lambda: self._stage_reflect(job),
            on_stage,
        )
        if not report.success:
            # reflect 失败但非致命
            pass

        return final_answer

    async def _run_stage(
        self,
        job: FeishuRenderJob,
        stage: RunnerStage,
        stage_fn: Callable[[], Awaitable[StageReport]],
        on_stage: Callable[[RunnerStage, str], Awaitable[None]] | None,
    ) -> StageReport:
        """运行单个阶段"""
        start = time.monotonic()

        # 更新可见状态
        job.update_visible_state(stage.value)

        # 通知阶段更新
        if on_stage:
            await on_stage(stage, f"正在 {stage.value}...")

        try:
            report = await stage_fn()
        except Exception as e:
            report = StageReport(
                stage=stage,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

        self._stage_reports.append(report)
        return report

    async def _stage_prepare(self, job: FeishuRenderJob) -> StageReport:
        """Stage 1: 准备工作"""
        start = time.monotonic()
        try:
            # 验证附件状态
            for att in job.attachments:
                if att.status in ("missing_local_path", "missing_file"):
                    # 附件不可用，记录但继续
                    pass

            return StageReport(
                stage=RunnerStage.PREPARE,
                success=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"attachments": len(job.attachments)},
            )
        except Exception as e:
            return StageReport(
                stage=RunnerStage.PREPARE,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    async def _stage_context(self, job: FeishuRenderJob) -> StageReport:
        """Stage 2: MemoryX 上下文构建"""
        start = time.monotonic()
        try:
            if not hasattr(self.memoryx_provider, "build_context"):
                return StageReport(
                    stage=RunnerStage.CONTEXT,
                    success=True,
                    duration_ms=0,
                    metadata={"reason": "no_memoryx_provider"},
                )

            context = await self.memoryx_provider.build_context(
                query=job.text,
                session_id=job.job_id,
            )
            job.context_summary = context[:500] if context else ""

            # 记录工具调用
            tool = ToolCallRecord(
                id="memoryx_context",
                name="memoryx_search",
                phase=ToolPhase.CONTEXT,
                status="done",
                user_visible_name="MemoryX 检索",
                summary=f"召回上下文 {len(context)} 字符" if context else "无相关记忆",
                started_at=time.strftime("%H:%M:%S"),
                finished_at=time.strftime("%H:%M:%S"),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            job.tools.append(tool)

            return StageReport(
                stage=RunnerStage.CONTEXT,
                success=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"context_length": len(job.context_summary)},
            )
        except Exception as e:
            return StageReport(
                stage=RunnerStage.CONTEXT,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    async def _stage_generate(
        self,
        job: FeishuRenderJob,
        on_delta: Callable[[str], Awaitable[None]],
        on_tool: Callable[[ToolCallRecord], Awaitable[None]],
    ) -> StageReport:
        """Stage 3: Hermes LLM 生成"""
        start = time.monotonic()
        try:
            if not hasattr(self.hermes_client, "generate"):
                # Mock 模式：直接返回输入
                job.answer = f"[模拟响应] {job.text}"
                return StageReport(
                    stage=RunnerStage.GENERATE,
                    success=True,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    metadata={"mode": "mock"},
                )

            # 调用 Hermes 生成
            async for delta in self.hermes_client.generate(
                prompt=job.text,
                context=job.context_summary,
                attachments=job.attachments,
                on_delta=on_delta,
                on_tool=on_tool,
                max_tokens=self.max_tokens,
            ):
                job.answer += delta

            return StageReport(
                stage=RunnerStage.GENERATE,
                success=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"answer_length": len(job.answer)},
            )
        except Exception as e:
            return StageReport(
                stage=RunnerStage.GENERATE,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    async def _stage_verify(self, job: FeishuRenderJob) -> StageReport:
        """Stage 4: Claim Guard 验证"""
        start = time.monotonic()
        try:
            if not hasattr(self.memoryx_provider, "verify_response"):
                return StageReport(
                    stage=RunnerStage.VERIFY,
                    success=True,
                    duration_ms=0,
                    metadata={"reason": "no_memoryx_provider"},
                )

            result = await self.memoryx_provider.verify_response(
                session_id=job.job_id,
                question=job.text,
                response=job.answer,
            )

            guard_decision = result.get("decision", "pass")
            warnings = result.get("warnings", [])

            # 记录工具调用
            tool = ToolCallRecord(
                id="claim_guard",
                name="claim_guard",
                phase=ToolPhase.GUARD,
                status="done" if guard_decision == "pass" else "warn",
                user_visible_name="Claim Guard",
                summary=f"验证通过" if guard_decision == "pass" else f"{len(warnings)} 条警告",
                started_at=time.strftime("%H:%M:%S"),
                finished_at=time.strftime("%H:%M:%S"),
                duration_ms=int((time.monotonic() - start) * 1000),
                guard_decision=guard_decision,
                severity="info" if guard_decision == "pass" else "warn",
            )
            job.tools.append(tool)

            if warnings:
                job.memoryx_badges.append(f"⚠️ {len(warnings)} 条警告")

            return StageReport(
                stage=RunnerStage.VERIFY,
                success=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"decision": guard_decision, "warnings": len(warnings)},
            )
        except Exception as e:
            return StageReport(
                stage=RunnerStage.VERIFY,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    async def _stage_reflect(self, job: FeishuRenderJob) -> StageReport:
        """Stage 5: 叙事反思"""
        start = time.monotonic()
        try:
            if not hasattr(self.memoryx_provider, "finalize_session"):
                return StageReport(
                    stage=RunnerStage.REFLECT,
                    success=True,
                    duration_ms=0,
                    metadata={"reason": "no_memoryx_provider"},
                )

            result = await self.memoryx_provider.finalize_session(
                session_id=job.job_id,
            )

            # 记录工具调用
            tool = ToolCallRecord(
                id="narrative_reflection",
                name="narrative_reflection",
                phase=ToolPhase.REFLECTION,
                status="done",
                user_visible_name="叙事反思",
                summary="已保存",
                started_at=time.strftime("%H:%M:%S"),
                finished_at=time.strftime("%H:%M:%S"),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            job.tools.append(tool)

            return StageReport(
                stage=RunnerStage.REFLECT,
                success=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata=result,
            )
        except Exception as e:
            return StageReport(
                stage=RunnerStage.REFLECT,
                success=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    def get_stage_reports(self) -> list[StageReport]:
        """获取所有阶段报告"""
        return list(self._stage_reports)
