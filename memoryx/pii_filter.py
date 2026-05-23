"""P2: PII 检测与 HMAC 匿名化。

检测: email, phone, CN ID, credit card, API key, bearer token, IPv4。
HMAC 稳定匿名化：同一原文始终生成同一匿名化结果。
默认不保留原文（本地配置控制）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Detection patterns ──────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)
_PHONE_CN_RE = re.compile(
    r"(?:(?:\+?86)?[-\s]?)?1[3-9]\d{9}",
)
_CN_ID_RE = re.compile(
    r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
)
_CREDIT_CARD_RE = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b",
)
_API_KEY_RE = re.compile(
    r"(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?key)[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})['\"]?",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"bearer\s+([A-Za-z0-9_\-\.]+=*)",
    re.IGNORECASE,
)
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
)


@dataclass
class PIISpan:
    """PII 检测结果 span。"""
    type: str           # email, phone, cn_id, credit_card, api_key, bearer, ipv4
    start: int          # 在原文中的起始位置
    end: int            # 结束位置
    original: str       # 原始值
    anonymized: str     # 匿名化后的值


@dataclass
class PIIResult:
    """PII 过滤结果。"""
    original_text: str
    anonymized_text: str
    spans: list[PIISpan] = field(default_factory=list)
    detected_count: int = 0

    @property
    def has_pii(self) -> bool:
        return self.detected_count > 0


class PIIFilter:
    """PII 检测 + HMAC 匿名化。

    HMAC 密钥来自 MEMORYX_PII_SECRET 环境变量，或默认 "memoryx-pii-default"。
    同一原文 + 同一密钥 → 同一匿名化结果（确定性）。
    """

    def __init__(self, *, secret: str | None = None) -> None:
        import os
        self.secret = (secret or os.environ.get("MEMORYX_PII_SECRET", "memoryx-pii-default")).encode("utf-8")

    # ── Public API ───────────────────────────────────────────────

    def detect(self, text: str) -> PIIResult:
        """检测文本中的 PII 并生成 span。"""
        spans: list[PIISpan] = []
        self._find_all(text, _EMAIL_RE, "email", spans)
        self._find_all(text, _PHONE_CN_RE, "phone_cn", spans)
        self._find_all(text, _CN_ID_RE, "cn_id", spans)
        self._find_all(text, _CREDIT_CARD_RE, "credit_card", spans)
        self._find_all(text, _API_KEY_RE, "api_key", spans)
        self._find_all(text, _BEARER_RE, "bearer", spans)
        self._find_all(text, _IPV4_RE, "ipv4", spans)

        # Sort by position, remove overlaps (keep earliest)
        spans.sort(key=lambda s: (s.start, -s.end))
        filtered: list[PIISpan] = []
        last_end = -1
        for s in spans:
            if s.start >= last_end:
                filtered.append(s)
                last_end = s.end

        return PIIResult(
            original_text=text,
            anonymized_text=self._anonymize_text(text, filtered),
            spans=filtered,
            detected_count=len(filtered),
        )

    def filter(self, text: str) -> str:
        """便捷方法：返回匿名化后的文本。"""
        return self.detect(text).anonymized_text

    def anonymize(self, value: str) -> str:
        """对单个值执行 HMAC 匿名化。"""
        return self._hmac_anonymize(value)

    # ── Internal ─────────────────────────────────────────────────

    def _find_all(
        self, text: str, pattern: re.Pattern, pii_type: str, spans: list[PIISpan],
    ) -> None:
        for m in pattern.finditer(text):
            original = m.group(0)
            # API key / bearer: extract only the key value, not the prefix
            if pii_type in ("api_key", "bearer"):
                original = m.group(1) if m.lastindex else m.group(0)
            spans.append(PIISpan(
                type=pii_type,
                start=m.start(),
                end=m.end(),
                original=original,
                anonymized=self._hmac_anonymize(original),
            ))

    def _hmac_anonymize(self, value: str) -> str:
        """HMAC-SHA256 稳定匿名化。"""
        h = hmac.new(self.secret, value.encode("utf-8"), hashlib.sha256)
        return f"<{h.hexdigest()[:12]}>"

    def _anonymize_text(self, text: str, spans: list[PIISpan]) -> str:
        """从后往前替换 span，避免位置偏移。"""
        result = text
        for s in reversed(spans):
            result = result[:s.start] + s.anonymized + result[s.end:]
        return result
