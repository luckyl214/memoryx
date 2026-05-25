"""卡片内容溢出处理 — 防长答案炸卡片。

飞书卡片内容有限制，超长内容需转为附件。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OverflowResult:
    card_text: str          # 放入卡片的内容
    overflow_text: str      # 溢出部分
    overflow: bool          # 是否溢出
    overflow_reason: str = ""  # 溢出原因


class CardOverflowPolicy:
    """卡片内容溢出策略"""

    def __init__(self, *, max_chars: int = 8000, max_bytes: int = 80_000) -> None:
        self.max_chars = max_chars
        self.max_bytes = max_bytes

    def split(self, text: str) -> OverflowResult:
        """将文本拆分为卡片内容和溢出内容"""
        raw = text or ""

        # 检查是否超限
        char_count = len(raw)
        byte_count = len(raw.encode("utf-8"))

        if char_count <= self.max_chars and byte_count <= self.max_bytes:
            return OverflowResult(
                card_text=raw,
                overflow_text="",
                overflow=False,
            )

        # 需要溢出处理
        # 预留后缀空间
        suffix = "\n\n…（完整内容已转为附件保存）"
        available = self.max_chars - len(suffix)

        # 优先按字符数截断
        card = raw[:available].rstrip()

        # 如果字节数仍超限，逐步缩短
        while len(card.encode("utf-8")) > self.max_bytes:
            card = card[:-1000].rstrip()

        # 确保截断在合理位置（句子边界）
        if len(card) > 100:
            # 尝试在句号/换行处截断
            last_break = max(
                card.rfind("。"),
                card.rfind("\n"),
                card.rfind(". "),
            )
            if last_break > len(card) // 2:
                card = card[: last_break + 1].rstrip()

        overflow = raw[len(card):].lstrip()

        return OverflowResult(
            card_text=card + suffix,
            overflow_text=overflow,
            overflow=True,
            overflow_reason=f"exceeded {self.max_chars} chars / {self.max_bytes} bytes",
        )

    def needs_overflow(self, text: str) -> bool:
        """检查是否需要溢出处理"""
        if not text:
            return False
        return len(text) > self.max_chars or len(text.encode("utf-8")) > self.max_bytes
