"""飞书输出策略 — 统一控制消息发送行为。

P14.4.2 Feishu Single-Card Live UX Hotfix:
- card_only 模式：只更新卡片，不发文本消息
- stream delta 只进卡片 timeline
- 工具输出只进工具时间线
- debug 日志只进 trace
- 内部工具信息（execute_code/python/bash）被过滤
"""
from __future__ import annotations

import os


INTERNAL_TOOL_NAMES = {
    "execute_code",
    "python",
    "python_exec",
    "shell",
    "bash",
    "terminal",
    "subprocess",
    "hermes",
}

NOISE_PATTERNS = [
    "execute_code:",
    "import os",
    "import sqlite3",
    "import yaml",
    "subprocess",
    "hermes_pa",
    "config_path",
    "sqlite3 ",
    "journalctl ",
    "systemctl ",
    "python -",
    "bash ",
    "curl ",
    "wget ",
    "git ",
    "pip ",
    "npm ",
]


class FeishuOutputPolicy:
    """飞书输出策略配置"""

    def __init__(self) -> None:
        self.output_mode = os.getenv("FEISHU_OUTPUT_MODE", "card_only")
        self.send_text_fallback = (
            os.getenv("FEISHU_SEND_TEXT_FALLBACK", "false").lower() == "true"
        )
        self.stream_text_messages = (
            os.getenv("FEISHU_STREAM_TEXT_MESSAGES", "false").lower() == "true"
        )

    def allow_text_message(self, *, reason: str) -> bool:
        """判断是否允许发送独立文本消息"""
        if self.output_mode == "card_only":
            return False
        if reason == "fatal_fallback":
            return self.send_text_fallback
        if reason == "stream_delta":
            return self.stream_text_messages
        if reason == "tool_output":
            return self.stream_text_messages
        return False

    def is_internal_noise(self, text: str) -> bool:
        """判断是否为内部工具输出噪音"""
        lower = text.lower()
        return any(p.lower() in lower for p in NOISE_PATTERNS)

    def should_show_tool(self, record) -> bool:
        """判断工具调用记录是否应展示在卡片上"""
        name = (getattr(record, "name", "") or "").lower()
        phase = (getattr(record, "phase", "") or "").lower()

        if name in INTERNAL_TOOL_NAMES:
            return False

        if phase in {"internal", "debug", "diagnostic"}:
            return False

        return True