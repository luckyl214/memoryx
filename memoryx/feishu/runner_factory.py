# memoryx/feishu/runner_factory.py
"""
Feishu runner factory — three-stage rollout.

  echo    → safe placeholder, verifies entry
  shadow  → real Hermes runs in background, user sees safe output
  real    → real Hermes output goes to user

Set FEISHU_RUNNER_MODE=echo|shadow|real in environment.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable

from .schemas import FeishuRenderJob, ToolCallRecord


# ── Echo Runner ──

class EchoFeishuRunner:
    """Safe placeholder — verifies feishu entry, queue, card updates."""

    async def __call__(
        self,
        job: FeishuRenderJob,
        on_delta: Callable[[str], Awaitable[None]],
        on_tool: Callable[[ToolCallRecord], Awaitable[None]],
        on_stage: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> str:
        await on_tool(ToolCallRecord(
            name="feishu_echo_runner",
            status="done",
            phase="system",
            summary="飞书入口已接通，当前使用 echo runner。",
        ))

        text = (
            "飞书入口已接通 ✅\n\n"
            "当前是占位 runner（echo），还没有调用真 Hermes。\n"
            "队列、卡片、状态机、附件链路已可验证。"
        )

        for i in range(0, len(text), 30):
            await on_delta(text[i:i+30])

        return text


# ── Shadow Runner ──

class ShadowFeishuRunner:
    """Run real Hermes in background, show safe echo output to user."""

    def __init__(self, real_runner: Any) -> None:
        self.real_runner = real_runner

    async def __call__(
        self,
        job: FeishuRenderJob,
        on_delta: Callable[[str], Awaitable[None]],
        on_tool: Callable[[ToolCallRecord], Awaitable[None]],
        on_stage: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> str:
        await on_tool(ToolCallRecord(
            name="feishu_shadow_runner",
            status="running",
            phase="system",
            summary="正在 shadow 模式验证真 Hermes runner。",
        ))

        shadow_deltas: list[str] = []
        shadow_tools: list[ToolCallRecord] = []

        async def shadow_delta(delta: str) -> None:
            shadow_deltas.append(delta)

        async def shadow_tool(tool: ToolCallRecord) -> None:
            shadow_tools.append(tool)

        try:
            answer = await asyncio.wait_for(
                self.real_runner(job, shadow_delta, shadow_tool, on_stage),
                timeout=300.0,
            )

            # Report shadow result to user card
            await on_tool(ToolCallRecord(
                name="feishu_shadow_runner",
                status="done",
                phase="system",
                summary=f"真 Hermes runner shadow 成功，{len(answer)} 字符。",
                output_preview=answer[:500],
            ))

            # Show safe output (same as echo)
            text = (
                "飞书入口已接通 ✅\n\n"
                "真 Hermes runner 已在 shadow 模式跑通，但本条消息仍为安全输出。\n"
                "下一步可将 FEISHU_RUNNER_MODE 切到 real。"
            )
            for i in range(0, len(text), 30):
                await on_delta(text[i:i+30])
            return text

        except TimeoutError:
            await on_tool(ToolCallRecord(
                name="feishu_shadow_runner",
                status="error",
                phase="system",
                summary="真 Hermes runner shadow 超时（300s）。",
            ))
            raise RuntimeError("Hermes shadow runner timed out after 300s")

        except Exception as exc:
            await on_tool(ToolCallRecord(
                name="feishu_shadow_runner",
                status="error",
                phase="system",
                summary=f"真 Hermes runner shadow 失败：{exc}",
            ))
            raise


# ── CLI-based Real Runner ──

class CLIHermesRunner:
    """Calls Hermes CLI via subprocess for real processing.

    Uses `hermes chat -q "..." --pass-session-id` per request.
    """

    def __init__(self, hermes_path: str = "hermes", timeout: float = 300.0) -> None:
        self.hermes_path = hermes_path
        self.timeout = timeout

    async def __call__(
        self,
        job: FeishuRenderJob,
        on_delta: Callable[[str], Awaitable[None]],
        on_tool: Callable[[ToolCallRecord], Awaitable[None]],
        on_stage: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> str:
        """Run a single Hermes query via CLI."""
        import subprocess

        if on_stage:
            await on_stage("hermes", "调用 Hermes CLI")

        # Build attachments description
        attachment_hint = ""
        if job.attachments:
            names = [a.name or a.kind for a in job.attachments if a.local_path]
            if names:
                attachment_hint = f"\n（已附附件：{', '.join(names)}）"

        prompt = job.text + attachment_hint

        cmd = [
            self.hermes_path,
            "chat",
            "-q", prompt,
            "--pass-session-id",
            "--source", f"feishu:{job.trace_id}",
            "-m", "deepseek-v4-flash",
            "--provider", "sensenova",
        ]

        await on_tool(ToolCallRecord(
            name="hermes_cli",
            status="running",
            phase="generate",
            summary=f"调用 Hermes CLI（{len(prompt)} 字符）",
            input_preview=prompt[:300],
        ))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                error_msg = stderr[:500] if stderr else f"exit code {process.returncode}"
                await on_tool(ToolCallRecord(
                    name="hermes_cli",
                    status="error",
                    phase="generate",
                    summary=error_msg,
                ))
                raise RuntimeError(f"Hermes CLI failed: {error_msg}")

            if not stdout:
                raise RuntimeError("Hermes CLI returned empty output")

            # Stream output as deltas
            for i in range(0, len(stdout), 30):
                await on_delta(stdout[i:i+30])

            await on_tool(ToolCallRecord(
                name="hermes_cli",
                status="done",
                phase="generate",
                summary=f"Hermes CLI 完成，{len(stdout)} 字符",
                output_preview=stdout[:500],
            ))

            return stdout

        except asyncio.TimeoutError:
            await on_tool(ToolCallRecord(
                name="hermes_cli",
                status="error",
                phase="generate",
                summary=f"Hermes CLI 超时（{self.timeout}s）",
            ))
            raise RuntimeError(f"Hermes CLI timed out after {self.timeout}s")


# ── MissingHermesClient placeholder ──

class MissingHermesClient:
    """Raise a clear error when Hermes is not configured."""

    async def stream(self, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Hermes client is not configured. "
            "Set FEISHU_RUNNER_MODE=echo or configure hermes_path."
        )


# ── Factory ──

def build_feishu_runner(*, real_runner: Any | None = None) -> Any:
    """Build feishu runner based on FEISHU_RUNNER_MODE.

    Modes:
      echo   → EchoFeishuRunner (default, safe)
      shadow → ShadowFeishuRunner wrapping real_runner
      real   → real_runner directly
    """
    mode = os.getenv("FEISHU_RUNNER_MODE", "echo").strip().lower()

    if mode == "echo":
        return EchoFeishuRunner()

    # Build default real runner if none provided
    if real_runner is None:
        real_runner = CLIHermesRunner()

    if mode == "shadow":
        return ShadowFeishuRunner(real_runner)

    if mode == "real":
        return real_runner

    raise RuntimeError(f"unknown FEISHU_RUNNER_MODE={mode!r}")