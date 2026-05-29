from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from memoryx.storage import StorageMaintenance


@dataclass(slots=True)
class SelfHealingReport:
    integrity_status: str
    repair_enabled: bool
    detected_issues: list[str] = field(default_factory=list)
    repaired_counts: dict[str, int] = field(default_factory=dict)
    maintenance_actions: list[str] = field(default_factory=list)


class SelfHealingEngine:
    def __init__(self, *, repository, stale_embedding_days: int = 30) -> None:
        self.repository = repository
        self.stale_embedding_days = stale_embedding_days
        self.maintenance = StorageMaintenance()

    async def run_once(self, *, repair: bool = True) -> SelfHealingReport:
        integrity_status = await self.maintenance.check_integrity(self.repository.db)
        report = SelfHealingReport(integrity_status=integrity_status, repair_enabled=repair)

        if integrity_status != "ok":
            report.detected_issues.append("storage_corruption")
            if repair:
                report.maintenance_actions.append("integrity_check_failed")

        checksum_count = await self._repair_checksum_drift(repair=repair)
        self._record_count(report, "checksum_drift", checksum_count)

        orphan_count = await self._repair_orphan_relations(repair=repair)
        self._record_count(report, "orphan_relations", orphan_count)

        stale_count = await self._mark_stale_embeddings(repair=repair)
        self._record_count(report, "stale_embeddings", stale_count)

        rebuilt = await self._rebuild_fts_index(repair=repair)
        self._record_count(report, "fts_rebuilt", rebuilt)

        return report

    async def _repair_checksum_drift(self, *, repair: bool) -> int:
        rows = await self.repository.db.fetchall("SELECT id AS memory_id, content, checksum FROM memories;")
        drifted = [dict(row) for row in rows if row["checksum"] != self.repository.checksum(str(row["content"]))]
        if not repair:
            return len(drifted)

        for row in drifted:
            expected = self.repository.checksum(str(row["content"]))
            memory_id = str(row["memory_id"])
            await self.repository.db.execute(
                "UPDATE memories SET checksum = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (expected, memory_id),
            )
            await self.repository.append_audit(
                "repair_checksum_drift",
                memory_id,
                "checksum_repaired",
                before_json={"old_checksum": row["checksum"], "new_checksum": expected},
            )
        return len(drifted)

    async def _repair_orphan_relations(self, *, repair: bool) -> int:
        rows = await self.repository.db.fetchall(
            """
            SELECT r.id AS relation_id
            FROM relations r
            LEFT JOIN entities source ON source.id = r.source_entity_id
            LEFT JOIN entities target ON target.id = r.target_entity_id
            WHERE source.id IS NULL OR target.id IS NULL;
            """
        )
        relation_ids = [str(row["relation_id"]) for row in rows]
        if not repair:
            return len(relation_ids)

        for relation_id in relation_ids:
            await self.repository.db.execute("DELETE FROM relations WHERE id = ?;", (relation_id,))
            await self.repository.append_audit(
                "repair_orphan_relation",
                relation_id,
                "orphan_removed",
                before_json={"relation_id": relation_id},
            )
        return len(relation_ids)

    async def _mark_stale_embeddings(self, *, repair: bool) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.stale_embedding_days)
        rows = await self.repository.db.fetchall(
            "SELECT memory_id, dimension, created_at FROM memory_embeddings WHERE datetime(created_at) < datetime(?);",
            (cutoff.isoformat(),),
        )
        stale_rows = [dict(row) for row in rows]
        if not repair:
            return len(stale_rows)

        for row in stale_rows:
            memory_id = str(row["memory_id"])
            await self.repository.append_audit(
                "embedding_refresh_needed",
                memory_id,
                "stale_embedding_detected",
                before_json={
                    "memory_id": memory_id,
                    "dimension": row.get("dimension"),
                    "created_at": row.get("created_at"),
                },
            )
        return len(stale_rows)

    def _record_count(self, report: SelfHealingReport, issue: str, count: int) -> None:
        if count <= 0:
            return
        report.detected_issues.append(issue)
        report.repaired_counts[issue] = count
        report.maintenance_actions.append(issue)

    async def _rebuild_fts_index(self, *, repair: bool) -> int:
        """重建 FTS 索引 — 崩溃恢复后修复损坏的全文搜索。"""
        try:
            row = await self.repository.db.fetchone("SELECT COUNT(*) AS cnt FROM memories_fts;")
            memory_count = int(row["cnt"]) if row else 0
            row2 = await self.repository.db.fetchone("SELECT COUNT(*) AS cnt FROM memories;")
            actual_count = int(row2["cnt"]) if row2 else 0
            if memory_count == actual_count:
                return 0
            if not repair:
                return actual_count - memory_count
            await self.repository.db.execute("DELETE FROM memories_fts;")
            rows = await self.repository.db.fetchall("SELECT id AS memory_id, content FROM memories;")
            for r in rows:
                await self.repository.db.execute(
                    "INSERT INTO memories_fts(memory_id, content) VALUES (?, ?);",
                    (str(r["memory_id"]), str(r["content"])),
                )
            return actual_count - memory_count
        except Exception:
            return 0
