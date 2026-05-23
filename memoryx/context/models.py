from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextBundle:
    rendered: str
    token_count: int
    truncated: bool = False
    used_summary_fallback: bool = False
    sections: dict[str, list[str]] = field(default_factory=dict)
