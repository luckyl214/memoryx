# memoryx/feishu/stream_sanitizer.py
"""
流清洗器：防止 Hermes/LLM 内部标记泄漏到飞书。

清理目标：
  - <|analysis|>, <|tool|>, <|commentary|> 等内部 token
  - [TOOL_CALL]...[/TOOL_CALL] 原始 JSON
  - scratchpad, chain_of_thought 等内部字段
  - 未闭合的代码块
  - 内部 guard block 原始 JSON
"""
from __future__ import annotations

import re


class StreamSanitizer:
    def __init__(self, *, max_chars: int = 12000) -> None:
        self.max_chars = max_chars
        self.patterns = [
            # 内部 token 标记
            re.compile(r"<\|/?(?:analysis|commentary|final|tool|assistant|system)[^|]*\|>", re.I),
            # TOOL_CALL 原始 JSON
            re.compile(r"\[TOOL_CALL\].*?\[/TOOL_CALL\]", re.I | re.S),
            # 内部标记
            re.compile(r"\[/?(?:analysis|tool_result|internal|scratchpad)\]", re.I),
            # 内部字段行
            re.compile(r"(?im)^\s*(analysis|chain[-_ ]?of[-_ ]?thought|scratchpad)\s*:\s*.*$", re.I),
            # 内部 JSON 代码块
            re.compile(r"```(?:json)?\s*\{\s*\"(?:tool|arguments|analysis|chain_of_thought)\".*?```", re.I | re.S),
        ]

    def clean(self, text: str) -> str:
        if not text:
            return ""

        out = text.replace("\r\n", "\n").replace("\r", "\n")

        for pattern in self.patterns:
            out = pattern.sub("", out)

        out = self._strip_unclosed_tool_json(out)
        out = self._balance_code_fences(out)
        out = re.sub(r"\n{4,}", "\n\n\n", out).strip()

        if len(out) > self.max_chars:
            out = out[: self.max_chars] + "\n\n…（内容过长，已截断；完整结果已保存到 MemoryX）"

        return out

    def _strip_unclosed_tool_json(self, text: str) -> str:
        """移除未闭合的工具调用 JSON"""
        idx = text.find('{"tool')
        if idx != -1 and text[idx:].count("{") > text[idx:].count("}"):
            return text[:idx].rstrip()
        return text

    def _balance_code_fences(self, text: str) -> str:
        """平衡代码块 fences"""
        if text.count("```") % 2 == 1:
            return text + "\n```"
        return text
