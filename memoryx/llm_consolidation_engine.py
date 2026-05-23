"""P5: LLMConsolidationEngine — LLM 驱动的记忆整合。

默认 dry-run，支持 daily token budget，无 key fallback。
操作：merge / supersede / mark_conflict / archive。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class ConsolidationResult:
    """整合结果。"""
    total_candidates: int = 0
    merged: int = 0
    superseded: int = 0
    conflicts_marked: int = 0
    archived: int = 0
    dry_run: bool = True
    actions: list[dict[str, Any]] = field(default_factory=list)
    token_used: int = 0


class LLMConsolidationEngine:
    """LLM 记忆整合引擎。

    渐进式替换 SemanticCompressionEngine 的旧聚类管线。
    """

    def __init__(self, *, repository, llm_client=None) -> None:
        self.repository = repository
        self.llm_client = llm_client  # optional: callable(text) -> str
        self._daily_token_budget: int = 100_000
        self._today_tokens: int = 0
        self._today_date: str = ""

    async def run(
        self,
        *,
        limit: int = 100,
        dry_run: bool = True,
        cluster_key: str | None = None,
    ) -> ConsolidationResult:
        """执行一轮记忆整合。

        Args:
            limit: 要检查的记忆数量
            dry_run: 仅预览不写入
            cluster_key: 可选聚类键
        """
        result = ConsolidationResult(dry_run=dry_run)
        self._reset_daily_budget()

        memories = await self.repository.list_active_memories(limit=limit)
        result.total_candidates = len(memories)

        if not memories:
            return result

        for memory in memories:
            action = self._analyze_memory(memory)
            if action is None:
                continue

            result.actions.append(action)
            action_type = action.get("type", "")

            if action_type == "merge" and not dry_run:
                target = action.get("target_id")
                if target:
                    await self.repository.supersede_memory(memory["id"], target)
                    result.merged += 1
            elif action_type == "supersede" and not dry_run:
                await self.repository.db.execute(
                    "UPDATE memories SET active_state = 'superseded', updated_at = datetime('now') WHERE id = ?;",
                    (memory["id"],),
                )
                result.superseded += 1
            elif action_type == "archive" and not dry_run:
                await self.repository.rollback_memory(memory["id"])
                result.archived += 1
            elif action_type == "conflict" and not dry_run:
                conflict_id = action.get("conflict_with")
                if conflict_id:
                    await self.repository.add_conflict(
                        memory["id"], conflict_id, action.get("reason", "llm_detected"),
                    )
                    result.conflicts_marked += 1

            if not dry_run and action_type == "merge":
                result.merged += 1
            elif dry_run and action_type:
                # Count in dry-run mode
                if action_type == "merge":
                    result.merged += 1
                elif action_type == "supersede":
                    result.superseded += 1
                elif action_type == "archive":
                    result.archived += 1
                elif action_type == "conflict":
                    result.conflicts_marked += 1

        # Reset counts in dry_run mode to actual (they won't be applied)
        if dry_run:
            result.merged = sum(1 for a in result.actions if a.get("type") == "merge")
            result.superseded = sum(1 for a in result.actions if a.get("type") == "supersede")
            result.archived = sum(1 for a in result.actions if a.get("type") == "archive")
            result.conflicts_marked = sum(1 for a in result.actions if a.get("type") == "conflict")

        return result

    def _analyze_memory(self, memory: dict) -> dict | None:
        """分析单条记忆的整合策略（LLM or heuristic fallback）。"""
        content = str(memory.get("content", ""))

        if self.llm_client and self._check_budget(200):
            return self._llm_analyze(content, memory)

        # Heuristic fallback (no LLM / no budget)
        return self._heuristic_analyze(memory)

    def _heuristic_analyze(self, memory: dict) -> dict | None:
        """无 LLM 时的启发式分析。"""
        content = str(memory.get("content", ""))
        decay = float(memory.get("decay_score", 0.0))
        access = int(memory.get("access_count", 0))
        confidence = float(memory.get("confidence_score", 1.0))

        # Archive: very decayed, never accessed
        if decay >= 0.95 and access == 0:
            return {"type": "archive", "reason": "high_decay_zero_access"}

        # Low confidence → mark conflict potential
        if confidence < 0.3:
            return {"type": "supersede", "reason": "low_confidence"}

        return None

    def _llm_analyze(self, content: str, memory: dict) -> dict | None:
        """LLM 分析（预留）。"""
        # Placeholder: actual LLM call would go here
        self._today_tokens += len(content.split())
        return None

    def _check_budget(self, needed: int) -> bool:
        return (self._today_tokens + needed) <= self._daily_token_budget

    def _reset_daily_budget(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today_date:
            self._today_tokens = 0
            self._today_date = today
