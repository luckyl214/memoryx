from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InjectedPrompt:
    rendered: str
    token_count: int
    truncated: bool = False
    used_summary_fallback: bool = False
