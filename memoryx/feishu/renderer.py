# memoryx/feishu/renderer.py
"""
飞书卡片渲染器：JSON 2.0 格式，运行态和最终态分离。

P14.4.3 硬化：
  - 固定输出 JSON 2.0 (schema: "2.0")
  - config.update_multi=true 支持动态 patch
  - final_view=True 只显示最终结果、耗时、执行摘要
  - 内部工具输出被 sanitizer 过滤，不进飞书
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from .schemas import AttachmentRef, FeishuRenderJob, HermesRunState, ToolCallRecord
from .stream_sanitizer import StreamSanitizer
from .render_text import attachment_status_text


CST = timezone(timedelta(hours=8))  # Asia/Shanghai 北京时间


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

# P14.4.3: 可见状态映射（8 类明确状态 + 视觉层级）
VISIBLE_STATE_META = {
    "received":    {"emoji": "📥", "label": "已收到",    "color": "blue"},
    "queued":      {"emoji": "⏳", "label": "排队中",    "color": "blue"},
    "thinking":    {"emoji": "🧠", "label": "正在处理",  "color": "blue"},
    "generating":  {"emoji": "✍️", "label": "生成中",    "color": "blue"},
    "verifying":   {"emoji": "🛡️", "label": "校验中",    "color": "yellow"},
    "using_tools": {"emoji": "🛠️", "label": "调用工具中", "color": "blue"},
    "waiting_user":{"emoji": "🟡", "label": "等待确认",  "color": "yellow"},
    "writing":     {"emoji": "✍️", "label": "整理答案中", "color": "blue"},
    "done":        {"emoji": "✅", "label": "已完成",    "color": "green"},
    "degraded":    {"emoji": "🟠", "label": "降级完成",  "color": "yellow"},
    "error":       {"emoji": "🔴", "label": "失败",     "color": "red"},
}


def format_cst(ts: float | None) -> str:
    if ts:
        return datetime.fromtimestamp(float(ts), CST).strftime("%Y-%m-%d %H:%M:%S CST")
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")


class FeishuCardRenderer:
    def __init__(self, *, max_answer_chars: int = 9000, max_tool_rows: int = 8) -> None:
        self.sanitizer = StreamSanitizer(max_chars=max_answer_chars)
        self.max_tool_rows = max_tool_rows

    def render(self, job: FeishuRenderJob, *, final_view: bool = False) -> dict[str, Any]:
        """
        渲染飞书卡片。
        
        Args:
            job: 渲染任务对象
            final_view: True=最终结果视图（只显示结果、耗时、摘要）
                       False=运行态视图（显示进度、阶段、实时摘要）
        """
        # P14.3: 优先使用可见状态
        visible = job.visible_state.value if hasattr(job, 'visible_state') else job.state
        vs_meta = VISIBLE_STATE_META.get(visible, VISIBLE_STATE_META["queued"])
        state = HermesRunState(job.state)
        meta = STATE_META[state]
        
        # 确保元素不超过 200（飞书限制）
        elements: list[dict[str, Any]] = []

        # 头部信息（动态更新：状态、任务摘要、trace）
        task_summary = job.text.strip()[:50] if job.text.strip() else (job.title or "Hermes · MemoryX")
        trace_info = f"rev {job.revision} · {job.phase or '—'}"
        if job.trace_id:
            trace_info = f"{job.trace_id[:12]} · {trace_info}"

        elements.append(self._kv_strip([
            ("状态", f"{vs_meta['emoji']} {vs_meta['label']}"),
            ("任务", task_summary),
            ("Trace", trace_info),
        ]))

        # MemoryX 状态徽章
        if job.memoryx_badges:
            elements.append(self._note(" · ".join(job.memoryx_badges[:6])))

        if final_view:
            # 最终视图：只显示结果、耗时、执行摘要
            elements.extend(self._final_elements(job))
        else:
            # 运行视图：显示进度、阶段、实时摘要
            elements.extend(self._live_elements(job))

        # 页脚
        elements.append({"tag": "hr"})
        elements.append(self._note(f"MemoryX · Hermes Cognitive Spine · {format_cst(getattr(job, 'updated_at', None))}"))

        return {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "width_mode": "fill",
                "summary": {
                    "content": f"Hermes · MemoryX · {vs_meta['label']}",
                },
            },
            "header": {
                "template": vs_meta["color"],
                "title": {
                    "tag": "plain_text",
                    "content": f"{vs_meta['emoji']} Hermes · MemoryX · {vs_meta['label']}",
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": format_cst(getattr(job, "updated_at", None)),
                },
            },
            "body": {
                "elements": elements[:180],  # 留 20 个元素余量
            },
        }

    def _live_elements(self, job: FeishuRenderJob) -> list[dict[str, Any]]:
        """运行态视图元素：显示进度、阶段、实时摘要、动态耗时。"""
        elements = [
            self.md("输入", self._input_summary(job)),
            self.md("当前阶段", self._phase_text(job)),
            self.md("执行进度", self._progress_text(job)),
            self.md("实时摘要", self._safe_preview(job)),
            self.md("耗时", self._duration(job)),
        ]

        # 附件信息（如果有）
        if job.attachments:
            elements.extend(self._attachments_block(job.attachments))

        return elements

    def _final_elements(self, job: FeishuRenderJob) -> list[dict[str, Any]]:
        """最终视图元素：只显示结果、耗时、执行摘要。"""
        answer = (getattr(job, "answer", "") or "").strip() or "已完成，但没有生成可展示文本。"

        elements = [
            self.md("最终结果", answer[:6000]),
            self.md("耗时", self._duration(job)),
            self.md("执行摘要", "MemoryX context → Hermes generate → guard → done"),
        ]

        # 如果有图片，整理后输出简洁摘要
        attachments = getattr(job, "attachments", None) or []
        images = [a for a in attachments if a.kind == "image"]
        files = [a for a in attachments if a.kind == "file"]
        if images or files:
            parts = []
            if images:
                parts.append(f"包含 {len(images)} 张图片，已用于分析")
            if files:
                parts.append(f"{len(files)} 个文件已保存")
            elements.append(self.md("附件摘要", "；".join(parts)))

        return elements

    def _input_summary(self, job: FeishuRenderJob) -> str:
        attachments = getattr(job, "attachments", None) or []
        if not attachments:
            return "已收到文本消息。"
        return f"已收到 {len(attachments)} 个附件，正在安全处理。"

    def _phase_text(self, job: FeishuRenderJob) -> str:
        mapping = {
            "received": "已收到请求",
            "prepare": "正在准备输入和附件",
            "context": "正在加载 MemoryX 上下文",
            "generate": "Hermes 正在生成回答",
            "verify": "正在执行 Claim Guard",
            "finalize": "正在整理最终结果",
            "done": "已完成",
            "error": "处理失败",
        }
        return mapping.get(getattr(job, "phase", "") or "", "处理中")

    def _progress_text(self, job: FeishuRenderJob) -> str:
        marks = getattr(job, "phase_marks", None) or []
        if not marks:
            return f"start → {job.phase or '—'}"
        return " → ".join(marks[-6:])

    def _safe_preview(self, job: FeishuRenderJob) -> str:
        """安全预览：过滤内部工具输出，只展示有意义的文本。"""
        text = (getattr(job, "stream_preview", "") or "").strip()
        if not text:
            return "正在处理，完成后会在本卡片内展示最终结果。"

        # 过滤内部工具输出
        banned = [
            "execute_code",
            "import os",
            "sqlite3",
            "subprocess",
            "systemctl",
            "journalctl",
            "yaml",
            "curl ",
            "bash ",
        ]

        lower = text.lower()
        if any(x in lower for x in banned):
            return "内部工具执行中，调试细节已写入 trace，不在飞书展示。"

        return text[-1200:]

    def _duration(self, job: FeishuRenderJob) -> str:
        started = getattr(job, "started_at", None) or getattr(job, "created_at", None)
        ended = getattr(job, "ended_at", None) or getattr(job, "updated_at", None)
        try:
            sec = max(0, int(float(ended) - float(started)))
            if sec < 60:
                return f"{sec} 秒"
            return f"{sec // 60} 分 {sec % 60} 秒"
        except Exception:
            return "—"

    def _attachments_block(self, attachments: list[AttachmentRef]) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []
        images = [a for a in attachments if a.kind == "image" and a.image_key]
        files = [a for a in attachments if not (a.kind == "image" and a.image_key)]

        if images:
            elements.append(self.md("图片", f"{len(images)} 张图片已安全入队"))
            for a in images[:3]:
                elements.append(self.md(a.name or 'image', f"![{a.name or 'image'}]({a.image_key})"))

        if files:
            lines = [f"{len(files)} 个文件已安全入队"]
            for a in files[:5]:
                size = f" · {self._format_size(a.size)}" if a.size else ""
                key = a.file_key or a.image_key or "queued"
                lines.append(f"- 📎 {a.name or key}{size}")
            elements.append(self.md("文件", "\n".join(lines)))

        return elements

    def md(self, title: str, content: str) -> dict[str, Any]:
        return {
            "tag": "markdown",
            "element_id": self._eid(title),
            "content": f"**{title}**\n{content}",
        }

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

    def _note(self, content: str) -> dict[str, Any]:
        # V2: note tag 已废弃，改用 div + lark_md
        return {
            "tag": "div",
            "text": {"tag": "lark_md", "content": content[:300]},
        }

    def _eid(self, title: str) -> str:
        mapping = {
            "状态": "state",
            "任务": "task",
            "Trace": "trace",
            "输入": "input",
            "当前阶段": "phase",
            "执行进度": "progress",
            "实时摘要": "preview",
            "最终结果": "result",
            "耗时": "duration",
            "执行摘要": "summary",
            "附件摘要": "attachments-summary",
            "图片": "images",
            "文件": "files",
            "下一步": "next-steps",
            "系统诊断": "diagnosis",
        }
        return mapping.get(title, "block")

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
