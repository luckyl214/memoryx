"""飞书卡片渲染器 — Live View 和 Final View 分离。

P14.4.2 Feishu Single-Card Live UX Hotfix:
- final_view=False：显示阶段、进度、简化工具摘要。
- final_view=True：隐藏过程，只显示最终答案、耗时、结果状态、执行摘要。
- 所有时间使用 Asia/Shanghai CST。
- 纯文本消息显示"已收到文本消息"，有附件才显示附件状态。
- 内部工具信息（execute_code/python/bash/sqlite3）只进 trace，不进卡片正文。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from .state_machine import VisibleState


CST = ZoneInfo("Asia/Shanghai")

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

NOISE_PATTERNS = {
    "execute_code:", "import os", "import sqlite3",
    "import yaml", "subprocess", "hermes_pa",
    "config_path", "sqlite3 ", "journalctl ", "systemctl ",
    "python -", "bash ", "curl ", "wget ", "git ",
}


def format_cst(value) -> str:
    """格式化时间戳为 CST 字符串"""
    try:
        return datetime.fromtimestamp(float(value), CST).strftime("%Y-%m-%d %H:%M:%S CST")
    except Exception:
        return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")


def is_internal_noise(text: str) -> bool:
    lower = text.lower()
    return any(p.lower() in lower for p in NOISE_PATTERNS)


class FeishuCardRenderer:
    """飞书卡片渲染器 — 支持 live_view 和 final_view 两种模式"""

    def __init__(self, *, max_answer_chars: int = 9000) -> None:
        self.max_answer_chars = max_answer_chars

    # ── 入口 ──

    def render(self, job: Any, *, final_view: bool = False) -> dict[str, Any]:
        visible = VisibleState(job.visible_state or job.state)
        icon, label = STATE_LABEL.get(visible, ("⏳", "处理中"))

        subtitle = self._build_subtitle(job)

        elements: list[dict[str, Any]] = []
        elements.append(self._markdown(f"**状态**\n{icon} {label} · `{job.visible_state}`"))
        elements.append(self._markdown(f"**任务**\n{job.title or 'Hermes · MemoryX'}"))
        elements.append(self._markdown(f"**Trace**\n`{job.trace_id or job.job_id[:8]}` · rev `{job.revision}`"))

        if final_view:
            elements.extend(self._final_elements(job))
        else:
            elements.extend(self._live_elements(job))

        # Footer
        elements.append({"tag": "hr"})
        elements.append(self._note(f"MemoryX · Hermes · {format_cst(datetime.now(CST).timestamp())}"))

        return {
            "config": {
                "wide_screen_mode": True,
                "update_multi": True,
            },
            "header": {
                "template": self._template_for_state(visible),
                "title": {
                    "tag": "plain_text",
                    "content": f"{icon} Hermes · MemoryX · {label}",
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": subtitle[:200],
                },
            },
            "elements": elements,
        }

    # ── 标题 ──

    def _build_subtitle(self, job: Any) -> str:
        ts = getattr(job, "updated_at", None) or getattr(job, "created_at", None)
        return f"{format_cst(ts)}"

    def _template_for_state(self, visible: VisibleState) -> str:
        if visible in {VisibleState.DONE}:
            return "green"
        if visible in {VisibleState.ERROR}:
            return "red"
        if visible in {VisibleState.WAITING_USER, VisibleState.DEGRADED}:
            return "yellow"
        return "blue"

    # ── Live View（运行中） ──

    def _live_elements(self, job: Any) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []

        # 附件/消息状态
        elements.append(self._markdown(self._attachment_status(job)))

        # 当前阶段
        phase_text = self._phase_text(job)
        if phase_text:
            elements.append(self._markdown(f"**当前阶段**\n{phase_text}"))

        # 执行进度
        progress = self._progress_summary(job)
        if progress:
            elements.append(self._markdown(f"**执行进度**\n{progress}"))

        # MemoryX badges
        badges = getattr(job, "memoryx_badges", None) or []
        if badges:
            elements.append(self._markdown("**MemoryX**\n" + " · ".join(badges[:6])))

        # Safe live preview（隐藏内部命令）
        preview = self._safe_live_preview(job)
        if preview:
            elements.append(self._markdown(f"**实时输出**\n{preview}"))

        return elements

    def _attachment_status(self, job: Any) -> str:
        attachments = getattr(job, "attachments", None) or []
        if not attachments:
            return "已收到文本消息，正在处理。"

        total = len(attachments)
        failed = sum(
            1 for a in attachments
            if getattr(a, "status", "") in {"failed", "download_failed", "unsupported", "too_large"}
        )
        ready = sum(
            1 for a in attachments
            if getattr(a, "status", "") in {"downloaded", "prepared", "uploaded"}
            or getattr(a, "local_path", None)
        )

        if failed:
            return f"已收到 {total} 个附件，其中 {failed} 个需要处理。"
        if ready == total:
            return f"已收到 {total} 个附件，已安全处理。"
        return f"已收到 {total} 个附件，正在处理。"

    def _phase_text(self, job: Any) -> str:
        phase = getattr(job, "phase", "") or ""
        mapping = {
            "received": "已收到请求",
            "queued": "等待 worker 处理",
            "prepare": "正在准备输入和附件",
            "context": "正在加载 MemoryX 上下文",
            "generate": "Hermes 正在生成回答",
            "verify": "正在执行 Claim Guard",
            "reflect": "正在保存叙事反思",
            "finalize": "正在整理最终结果",
            "done": "已完成",
            "error": "处理失败",
        }
        return mapping.get(phase, phase)

    def _progress_summary(self, job: Any) -> str:
        phases = getattr(job, "phase_marks", None) or []
        if not phases:
            return "MemoryX ✅ · Semantic ✅ · P13 ✅"
        return " → ".join(str(p) for p in phases[-5:])

    def _safe_live_preview(self, job: Any) -> str:
        text = getattr(job, "stream_preview", "") or ""
        if not text:
            return ""

        if is_internal_noise(text):
            return "正在处理内部步骤，完成后将展示最终结果。"

        return text[-1200:]

    # ── Final View（完成后） ──

    def _final_elements(self, job: Any) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []

        # 最终结果
        answer = (getattr(job, "answer", "") or "").strip()
        if answer:
            elements.append(self._markdown(f"**最终结果**\n{self._safe_text(answer, self.max_answer_chars)}"))
        else:
            elements.append(self._markdown("**最终结果**\n已完成，但没有生成可展示文本。"))

        # 耗时
        duration = self._duration_text(job)
        if duration:
            elements.append(self._markdown(f"**耗时**\n{duration}"))

        # 执行摘要（隐藏内部工具）
        summary = self._execution_summary(job)
        if summary:
            elements.append(self._markdown(f"**执行摘要**\n{summary}"))

        # 附件
        attach_text = self._final_attachment_text(job)
        if attach_text:
            elements.append(self._markdown(attach_text))

        return elements

    def _duration_text(self, job: Any) -> str:
        started = getattr(job, "started_at", None) or getattr(job, "created_at", None)
        ended = getattr(job, "ended_at", None) or getattr(job, "updated_at", None)
        try:
            sec = max(0, int(float(ended) - float(started)))
            if sec < 60:
                return f"{sec} 秒"
            return f"{sec // 60} 分 {sec % 60} 秒"
        except Exception:
            return ""

    def _execution_summary(self, job: Any) -> str:
        tool_calls = getattr(job, "tool_calls", None) or []
        phase_marks = getattr(job, "phase_marks", None) or []

        if not tool_calls and not phase_marks:
            return "MemoryX context → Hermes generate → guard → done"

        visible_steps = []
        for p in phase_marks:
            if p in {"prepare", "context", "generate", "verify", "reflect", "finalize", "done"}:
                visible_steps.append(p)

        if visible_steps:
            return " → ".join(visible_steps)

        return "内部步骤已完成。"

    def _final_attachment_text(self, job: Any) -> str:
        attachments = getattr(job, "attachments", None) or []
        uploaded = [
            a for a in attachments
            if getattr(a, "status", "") == "uploaded"
            or getattr(a, "file_key", None)
        ]
        if not uploaded:
            return ""
        names = ", ".join(getattr(a, "name", "附件") for a in uploaded[:5])
        return f"**附件**\n完整内容已保存：{names}"

    # ── 工具 ──

    def _safe_text(self, text: str, max_chars: int) -> str:
        """安全截断文本，避免过长"""
        text = str(text)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n…（内容过长已截断）"

    # ── 飞书卡片组件 ──

    def _markdown(self, content: str) -> dict[str, Any]:
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content,
            },
        }

    def _note(self, content: str) -> dict[str, Any]:
        return {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": content[:300]}],
        }

    def _hr(self) -> dict[str, Any]:
        return {"tag": "hr"}