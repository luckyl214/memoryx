"""飞书输出策略 — 统一控制发送行为，禁止刷屏。

原则：
1. card_only 模式：只更新同一张卡片，不发任何短消息
2. stream delta 只进卡片，不进飞书消息流
3. 工具日志、命令输出进卡片 tool timeline，不单独发送
"""
from __future__ import annotations

import os


class FeishuOutputPolicy:
    """飞书输出策略 — 统一出口，防止短消息刷屏。"""

    def __init__(self) -> None:
        self.output_mode = os.getenv("FEISHU_OUTPUT_MODE", "card_only")
        self.send_text_fallback = os.getenv("FEISHU_SEND_TEXT_FALLBACK", "false").lower() == "true"
        self.stream_text_messages = os.getenv("FEISHU_STREAM_TEXT_MESSAGES", "false").lower() == "true"

    def allow_text_message(self, *, reason: str) -> bool:
        """判断是否允许发送独立文本消息。

        reason 取值：
          - "fatal_fallback": 卡片完全发不了，最后的降级
          - "stream_delta":   stream 增量
          - "tool_output":    工具输出
          - "command_output": 命令输出
        """
        if self.output_mode == "card_only":
            return False
        if reason == "fatal_fallback":
            return self.send_text_fallback
        if reason == "stream_delta":
            return self.stream_text_messages
        return False
