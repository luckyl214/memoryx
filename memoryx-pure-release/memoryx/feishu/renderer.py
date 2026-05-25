# memoryx/feishu/renderer.py
"""
飞书卡片渲染器：三状态 + 工具调用 + 图文混排。

状态：
  queued   排队中  grey
  running  处理中  blue
  done     已完成  green
  error    失败    red（异常状态）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import AttachmentRef, FeishuRenderJob, HermesRunState, ToolCallRecord
from .stream_sanitizer import StreamSanitizer


STATE_META = {
    HermesRunState.QUEUED: {
        "label": "排队中",
        "emoji": "⏳",
        "template": "grey",
        "hint": "已收到，附件已安全入队。",
    },
    HermesRunState.RUNNING: {
        "label": "处理中",
        "emoji": "🔵",
        "template": "blue",
        "hint": "Hermes 正在思考或调用工具。",
    },
    HermesRunState.DONE: {
        "label": "已完成",
        "emoji": "✅",
        "template": "green",
        "hint": "结果已生成，并写入 MemoryX。",
    },
    HermesRunState.ERROR: {
        "label": "失败",
        "emoji": "🔴",
        "template": "red",
        "hint": "处理失败，附件仍保存在队列中，可重试。",
    },
}

# P14.3: 可见状态映射
VISIBLE_STATE_META = {
    "received":    {"emoji": "📥", "label": "已收到",    "color": "grey"},
    "queued":      {"emoji": "⏳", "label": "排队中",    "color": "grey"},
    "thinking":    {"emoji": "🧠", "label": "思考中",    "color": "blue"},
    "using_tools": {"emoji": "🛠️", "label": "调用工具中", "color": "blue"},
    "waiting_user":{"emoji": "🟡", "label": "等待确认",  "color": "yellow"},
    "writing":     {"emoji": "✍️", "label": "整理答案中", "color": "blue"},
    "done":        {"emoji": "✅", "label": "已完成",    "color": "green"},
    "degraded":    {"emoji": "🟠", "label": "降级完成",  "color": "yellow"},
    "error":       {"emoji": "🔴", "label": "失败",     "color": "red"},
}


class FeishuCardRenderer:
    def __init__(self, *, max_answer_chars: int = 9000, max_tool_rows: int = 8) -> None:
        self.sanitizer = StreamSanitizer(max_chars=max_answer_chars)
        self.max_tool_rows = max_tool_rows

    def render(self, job: FeishuRenderJob) -> dict[str, Any]:
        # P14.3: 优先使用可见状态
        visible = job.visible_state.value if hasattr(job, 'visible_state') else job.state
        vs_meta = VISIBLE_STATE_META.get(visible, VISIBLE_STATE_META["queued"])
        state = HermesRunState(job.state)
        meta = STATE_META[state]
        elements: list[dict[str, Any]] = []

        # 头部信息（P14.3: 显示 revision 和 phase）
        revision_info = f" rev {job.revision}" if job.revision > 0 else ""
        phase_info = f" · {job.phase}" if hasattr(job, 'phase') and job.phase else ""
        elements.append(self._kv_strip([
            ("状态", f"{vs_meta['emoji']} {vs_meta['label']}{phase_info}"),
            ("任务", job.title),
            ("Trace", f"{job.trace_id or job.job_id[:10]}{revision_info}"),
        ]))

        # MemoryX 状态徽章
        if job.memoryx_badges:
            elements.append(self._note(" · ".join(job.memoryx_badges[:6])))

        # MemoryX 上下文
        if job.context_summary:
            elements.append(self._markdown("**MemoryX 上下文**\n" + self._md(job.context_summary)))

        # 附件
        if job.attachments:
            elements.extend(self._attachments_block(job.attachments))

        # 工具调用记录
        if job.tools:
            elements.append(self._markdown("**工具调用记录**"))
            elements.extend(self._tool_blocks(job.tools[: self.max_tool_rows]))
            if len(job.tools) > self.max_tool_rows:
                elements.append(self._note(f"还有 {len(job.tools) - self.max_tool_rows} 条工具记录已折叠。"))

        # 结构化正文
        answer = self.sanitizer.clean(job.answer)
        if answer:
            elements.append(self._markdown("**结构化正文**\n" + self._md(answer)))
        elif state in {HermesRunState.QUEUED, HermesRunState.RUNNING}:
            elements.append(self._markdown(self._md(meta["hint"])))

        # 错误信息
        if job.error:
            elements.append(self._markdown("**错误信息**\n<font color='red'>" + self._md(job.error) + "</font>"))

        # 页脚
        elements.append({"tag": "hr"})
        elements.append(self._note(f"MemoryX · Hermes Cognitive Spine · {self._now()}"))

        return {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": vs_meta["color"],
                "title": {
                    "tag": "plain_text",
                    "content": f"{vs_meta['emoji']} {job.title} · {vs_meta['label']}",
                },
            },
            "elements": elements,
        }

    def _tool_blocks(self, tools: list[ToolCallRecord]) -> list[dict[str, Any]]:
        blocks = []
        for tool in tools:
            icon = {
                "running": "⏳",
                "done": "✅",
                "error": "🔴",
                "skipped": "⚪",
            }.get(tool.status, "•")

            lines = [f"{icon} **{self._md(tool.name)}** · {self._md(tool.status)}"]

            if tool.guard_decision:
                lines.append(f"Guard: `{self._md(tool.guard_decision)}`")
            if tool.summary:
                lines.append(self._md(tool.summary))
            if tool.input_preview:
                lines.append(f"输入：`{self._md(tool.input_preview[:300])}`")
            if tool.output_preview:
                lines.append(f"输出：{self._md(tool.output_preview[:500])}")
            if tool.duration_ms is not None:
                lines.append(f"耗时：{tool.duration_ms}ms")

            blocks.append(self._markdown("\n".join(lines)))
        return blocks

    def _attachments_block(self, attachments: list[AttachmentRef]) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []
        images = [a for a in attachments if a.kind == "image" and a.image_key]
        files = [a for a in attachments if not (a.kind == "image" and a.image_key)]

        if images:
            elements.append(self._markdown("**图片**"))
            for a in images[:6]:
                elements.append(self._markdown(f"![{self._md(a.name or 'image')}]({a.image_key})"))
            if len(images) > 6:
                elements.append(self._note(f"还有 {len(images) - 6} 张图片已保存，未在卡片中展开。"))

        if files:
            lines = ["**文件**"]
            for a in files[:10]:
                size = f" · {self._format_size(a.size)}" if a.size else ""
                key = a.file_key or a.image_key or "queued"
                lines.append(f"- 📎 {self._md(a.name or key)}{size}")
            elements.append(self._markdown("\n".join(lines)))

        return elements

    def _kv_strip(self, pairs: list[tuple[str, str]]) -> dict[str, Any]:
        fields = []
        for k, v in pairs:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**{self._md(k)}**\n{self._md(v)}",
                },
            })
        return {"tag": "div", "fields": fields}

    def _markdown(self, content: str) -> dict[str, Any]:
        return {"tag": "markdown", "content": content}

    def _note(self, content: str) -> dict[str, Any]:
        return {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": content[:300]}],
        }

    def _md(self, text: str) -> str:
        text = "" if text is None else str(text)
        return text.replace("<", "‹").replace(">", "›")

    def _format_size(self, size: int | None) -> str:
        if not size:
            return ""
        value = float(size)
        for unit in ["B", "KB", "MB", "GB"]:
            if value < 1024 or unit == "GB":
                return f"{value:.1f}{unit}"
            value /= 1024
        return f"{size}B"

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
