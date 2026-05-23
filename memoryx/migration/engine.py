from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .adapters import AdapterRegistry, BaseAdapter

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """迁移报告 — 记录导入结果。"""
    source: str = ""
    adapter: str = ""
    total_scanned: int = 0
    imported: int = 0
    skipped_empty: int = 0
    skipped_duplicate: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MigrationEngine:
    """
    记忆迁移引擎 — 双向迁移。

    导入：从其他记忆系统 → memoryx
    导出：从 memoryx → 其他记忆系统格式

    支持的源/目标系统：
    tencentdb, holographic, hermes, mem0, hindsight, letta, zep, cognee, gbrain, json
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    async def migrate(
        self,
        *,
        source: str,
        source_path: str,
        deduplicate: bool = True,
        dry_run: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> MigrationReport:
        """导入：从源系统迁移到 memoryx。"""
        report = MigrationReport(source=source_path, adapter=source)

        adapter_cls = AdapterRegistry.get(source)
        adapter = adapter_cls()

        try:
            records = await adapter.scan(source_path)
            report.total_scanned = len(records)
        except Exception as e:
            report.errors.append(f"Scan failed: {e}")
            return report

        if not records:
            report.warnings.append("No records found")
            return report

        seen_content: set[str] = set()
        for record in records:
            normalized = adapter.normalize(record)
            content = normalized.get("content", "").strip()
            if not content:
                report.skipped_empty += 1
                continue
            if deduplicate:
                cl = content.lower()
                if cl in seen_content:
                    report.skipped_duplicate += 1
                    continue
                seen_content.add(cl)
            if dry_run:
                report.imported += 1
                continue
            try:
                memory = __import__("memoryx").storage.MemoryRecord(
                    memory_id=normalized["memory_id"],
                    memory_type=normalized["memory_type"],
                    content=normalized["content"],
                    scope=normalized.get("scope", "imported"),
                    importance_score=normalized.get("importance_score", 0.5),
                    confidence_score=normalized.get("confidence_score", 0.5),
                    tags_json=normalized.get("tags_json", "[]"),
                    source_message_id=normalized.get("source_message_id", ""),
                )
                await self.repository.store_memory(memory)
                report.imported += 1
            except Exception as e:
                report.errors.append(f"Import failed for {normalized.get('memory_id', '?')}: {e}")
            if progress_callback:
                progress_callback(report.imported, report.total_scanned)

        return report

    async def restore(
        self,
        *,
        target: str,
        target_path: str,
        limit: int = 5000,
        scope_filter: str | None = None,
    ) -> MigrationReport:
        """导出：从 memoryx 恢复到目标记忆系统。"""
        report = MigrationReport(source="memoryx", adapter=target)

        try:
            memories = await self.repository.list_active_memories(limit=limit)
            if scope_filter:
                memories = [m for m in memories if m.get("scope") == scope_filter]
        except Exception as e:
            report.errors.append(f"Read from memoryx failed: {e}")
            return report

        if not memories:
            report.warnings.append("No memories found to export")
            return report

        records = []
        for mem in memories:
            try:
                tags = json.loads(mem.get("tags_json", "[]") or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            records.append({
                "memory_id": str(mem["memory_id"]),
                "memory_type": str(mem.get("memory_type", "FACT")),
                "content": str(mem.get("content", "")),
                "scope": str(mem.get("scope", "imported")),
                "importance_score": float(mem.get("importance_score", 0.5)),
                "confidence_score": float(mem.get("confidence_score", 0.5)),
                "tags_json": json.dumps(tags),
                "tags": tags,
                "source_message_id": str(mem.get("source_message_id", "")),
            })

        adapter_cls = AdapterRegistry.get(target)
        adapter = adapter_cls()

        try:
            exported = await adapter.export(records, target_path)
            report.imported = exported
            report.total_scanned = len(records)
        except Exception as e:
            report.errors.append(f"Export failed: {e}")

        return report

    @staticmethod
    def list_adapters() -> list[str]:
        return AdapterRegistry.list()
