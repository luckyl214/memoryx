from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.types import MemoryCategory, MemoryLayer, MemorySource
from .migrations import MigrationManager
from .sqlite_async import AsyncSQLite


MEMORY_TYPES = {
    "FACT",
    "EXPERIENCE",
    "OBSERVATION",
    "OPINION",
    "PREFERENCE",
    "PROJECT",
    "TASK",
    "RELATION",
    "EPISODIC",
    "ENT_RELATION",
    "PERSONA",
}


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    memory_type: str
    content: str
    importance_score: float = 0.5
    confidence_score: float = 0.5
    decay_score: float = 0.0
    recency_score: float = 0.0
    access_count: int = 0
    checksum: str = ""
    superseded_by: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    active_state: int = 1
    reinforcement_score: float = 0.0
    safety_score: float = 1.0
    scope: str = "global"
    source_message_id: str | None = None
    entities_json: str = "[]"
    tags_json: str = "[]"
    # MAMS-inspired fields — backward-compatible defaults
    category: str = "session"
    layer: str = "working"
    source: str = "dialogue"


class MemoryRepository:
    def __init__(self, db_path: Path) -> None:
        self.db = AsyncSQLite(db_path)
        self.migrations = MigrationManager(db=self.db)

    async def open(self) -> None:
        await self.db.open()
        await self.migrations.ensure_schema()

    async def close(self) -> None:
        await self.db.close()

    @staticmethod
    def checksum(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _normalize_record(self, record: MemoryRecord) -> MemoryRecord:
        if record.memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unsupported memory_type: {record.memory_type}")
        if not record.checksum:
            record.checksum = self.checksum(record.content)
        if not record.valid_from:
            record.valid_from = datetime.now(timezone.utc).isoformat()
        if not record.category or record.category not in ("user", "session", "agent"):
            record.category = "session"
        if not record.layer or record.layer not in ("working", "short_term", "long_term", "archive", "self_edit"):
            record.layer = "working"
        if not record.source or record.source not in ("dialogue", "tool_result", "manual", "system"):
            record.source = "dialogue"
        return record

    def _normalize_search_query(self, query: str) -> str:
        tokens = [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in query).split() if token]
        if not tokens:
            return ""
        return " OR ".join(tokens)

    def _normalize_search_query_cn(self, query: str) -> str:
        """中文分词版 — 需要 jieba 库。"""
        try:
            import jieba
            tokens = [w for w in jieba.cut(query) if w.strip() and len(w.strip()) > 1]
            if tokens:
                return " OR ".join(tokens)
        except ImportError:
            pass
        return self._normalize_search_query(query)

    def _memory_params(self, record: MemoryRecord) -> tuple[Any, ...]:
        normalized = self._normalize_record(record)
        return (
            normalized.memory_id,
            normalized.memory_type,
            normalized.content,
            normalized.importance_score,
            normalized.confidence_score,
            normalized.decay_score,
            normalized.recency_score,
            normalized.access_count,
            normalized.checksum,
            normalized.superseded_by,
            normalized.valid_from,
            normalized.valid_to,
            normalized.active_state,
            normalized.reinforcement_score,
            normalized.safety_score,
            normalized.scope,
            normalized.source_message_id,
            normalized.entities_json,
            normalized.tags_json,
            normalized.category,
            normalized.layer,
            normalized.source,
        )

    async def store_memory(self, record: MemoryRecord) -> str:
        await self.db.execute(
            """
            INSERT INTO memories (
                memory_id, memory_type, content, importance_score, confidence_score,
                decay_score, recency_score, access_count, checksum, superseded_by,
                valid_from, valid_to, active_state, reinforcement_score, safety_score,
                scope, source_message_id, entities_json, tags_json,
                category, layer, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(memory_id) DO UPDATE SET
                memory_type=excluded.memory_type,
                content=excluded.content,
                importance_score=excluded.importance_score,
                confidence_score=excluded.confidence_score,
                decay_score=excluded.decay_score,
                recency_score=excluded.recency_score,
                access_count=excluded.access_count,
                checksum=excluded.checksum,
                superseded_by=excluded.superseded_by,
                valid_from=excluded.valid_from,
                valid_to=excluded.valid_to,
                active_state=excluded.active_state,
                reinforcement_score=excluded.reinforcement_score,
                safety_score=excluded.safety_score,
                scope=excluded.scope,
                source_message_id=excluded.source_message_id,
                entities_json=excluded.entities_json,
                tags_json=excluded.tags_json,
                category=excluded.category,
                layer=excluded.layer,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP;
            """,
            self._memory_params(record),
        )
        normalized = self._normalize_record(record)
        await self.append_audit("store_memory", normalized.memory_id, {"memory_type": normalized.memory_type, "checksum": normalized.checksum})
        await self.write_version(normalized.memory_id, normalized.content, normalized.checksum)
        return normalized.memory_id

    async def store_memories(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0
        params = [self._memory_params(record) for record in records]
        await self.db.executemany(
            """
            INSERT INTO memories (
                memory_id, memory_type, content, importance_score, confidence_score,
                decay_score, recency_score, access_count, checksum, superseded_by,
                valid_from, valid_to, active_state, reinforcement_score, safety_score,
                scope, source_message_id, entities_json, tags_json,
                category, layer, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(memory_id) DO UPDATE SET
                memory_type=excluded.memory_type,
                content=excluded.content,
                importance_score=excluded.importance_score,
                confidence_score=excluded.confidence_score,
                decay_score=excluded.decay_score,
                recency_score=excluded.recency_score,
                access_count=excluded.access_count,
                checksum=excluded.checksum,
                superseded_by=excluded.superseded_by,
                valid_from=excluded.valid_from,
                valid_to=excluded.valid_to,
                active_state=excluded.active_state,
                reinforcement_score=excluded.reinforcement_score,
                safety_score=excluded.safety_score,
                scope=excluded.scope,
                source_message_id=excluded.source_message_id,
                entities_json=excluded.entities_json,
                tags_json=excluded.tags_json,
                category=excluded.category,
                layer=excluded.layer,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP;
            """,
            params,
        )
        await asyncio.gather(
            *[
                self.append_audit("store_memory", record.memory_id, {"memory_type": record.memory_type, "checksum": record.checksum or self.checksum(record.content)})
                for record in records
            ],
            *[
                self.write_version(record.memory_id, record.content, record.checksum or self.checksum(record.content))
                for record in records
            ],
        )
        return len(records)

    async def write_version(self, memory_id: str, content: str, checksum: str) -> None:
        row = await self.db.fetchone("SELECT COALESCE(MAX(version_number), 0) AS version_number FROM memory_versions WHERE memory_id = ?;", (memory_id,))
        next_version = int(row["version_number"] if row else 0) + 1
        await self.db.execute(
            "INSERT INTO memory_versions(version_id, memory_id, version_number, content, checksum, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (uuid4().hex, memory_id, next_version, content, checksum),
        )

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM memories WHERE memory_id = ?;", (memory_id,))
        return dict(row) if row else None

    async def list_memories(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?;", (limit,))
        return [dict(row) for row in rows]

    async def list_active_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM memories WHERE active_state = 1 ORDER BY importance_score DESC, updated_at DESC LIMIT ?;",
            (limit,),
        )
        return [dict(row) for row in rows]

    async def search_full_text(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        normalized_query = self._normalize_search_query(query)
        if not normalized_query:
            return []
        rows = await self.db.fetchall(
            """
            SELECT m.*
            FROM memories_fts f
            JOIN memories m ON m.memory_id = f.memory_id
            WHERE memories_fts MATCH ?
            ORDER BY bm25(memories_fts)
            LIMIT ?;
            """,
            (normalized_query, limit),
        )
        return [dict(row) for row in rows]

    async def record_access(self, memory_id: str) -> None:
        await self.db.execute("UPDATE memories SET access_count = access_count + 1, updated_at = CURRENT_TIMESTAMP WHERE memory_id = ?;", (memory_id,))
        await self.db.execute(
            "INSERT INTO memory_access_logs(access_id, memory_id, accessed_at, access_type) VALUES (?, ?, CURRENT_TIMESTAMP, ?);",
            (uuid4().hex, memory_id, "read"),
        )

    async def supersede_memory(self, memory_id: str, superseded_by: str) -> None:
        await self.db.execute(
            "UPDATE memories SET active_state = 0, superseded_by = ?, valid_to = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE memory_id = ?;",
            (superseded_by, memory_id),
        )
        await self.append_audit("supersede_memory", memory_id, {"superseded_by": superseded_by})

    async def add_conflict(self, memory_id: str, conflicting_memory_id: str, reason: str) -> None:
        await self.db.execute(
            "INSERT INTO memory_conflicts(conflict_id, memory_id, conflicting_memory_id, reason, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (uuid4().hex, memory_id, conflicting_memory_id, reason),
        )
        await self.append_audit("conflict_detected", memory_id, {"conflicting_memory_id": conflicting_memory_id, "reason": reason})

    async def add_entity(self, entity_name: str, entity_type: str = "unknown", metadata_json: str = "{}") -> str:
        entity_id = uuid4().hex
        await self.db.execute(
            "INSERT INTO entities(entity_id, entity_name, entity_type, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (entity_id, entity_name, entity_type, metadata_json),
        )
        return entity_id

    async def add_relation(self, source_entity_id: str, target_entity_id: str, relation_type: str, weight: float = 1.0) -> str:
        relation_id = uuid4().hex
        await self.db.execute(
            "INSERT INTO relations(relation_id, source_entity_id, target_entity_id, relation_type, weight, created_at, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (relation_id, source_entity_id, target_entity_id, relation_type, weight),
        )
        return relation_id

    async def add_session_summary(self, session_id: str, summary: str, source_count: int = 0) -> None:
        await self.db.execute(
            "INSERT INTO session_summaries(summary_id, session_id, summary, source_count, created_at, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, source_count=excluded.source_count, updated_at=CURRENT_TIMESTAMP;",
            (uuid4().hex, session_id, summary, source_count),
        )

    async def add_episodic_memory(self, session_id: str, title: str, content: str, importance_score: float = 0.5) -> str:
        episodic_id = uuid4().hex
        await self.db.execute(
            "INSERT INTO episodic_memories(episodic_id, session_id, title, content, importance_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (episodic_id, session_id, title, content, importance_score),
        )
        return episodic_id

    async def quarantine_memory(self, memory_id: str, reason: str) -> None:
        await self.db.execute(
            "INSERT INTO safety_quarantine(quarantine_id, memory_id, reason, status, created_at, updated_at) VALUES (?, ?, ?, 'quarantined', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);",
            (uuid4().hex, memory_id, reason),
        )
        await self.append_audit("quarantine_memory", memory_id, {"reason": reason})

    async def append_audit(self, action: str, subject_id: str, payload: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT INTO audit_logs(audit_id, action, subject_id, payload_json, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (uuid4().hex, action, subject_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    async def replay_events(self, action: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """事件溯源 — 重放审计事件。"""
        if action:
            rows = await self.db.fetchall(
                "SELECT audit_id, action, subject_id, payload_json, created_at FROM audit_logs WHERE action = ? ORDER BY created_at ASC LIMIT ?;",
                (action, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT audit_id, action, subject_id, payload_json, created_at FROM audit_logs ORDER BY created_at ASC LIMIT ?;",
                (limit,),
            )
        return [dict(row) for row in rows]

    async def export_markdown(self, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rows = await self.db.fetchall("SELECT * FROM memories ORDER BY updated_at DESC;")
        path = output_dir / "memories.md"
        lines = ["# Memories", ""]
        for row in rows:
            item = dict(row)
            lines.append(f"- {item['memory_id']} [{item['memory_type']}] {item['content']}")
        await asyncio.to_thread(path.write_text, "\n".join(lines) + "\n", encoding="utf-8")
        return [path]

    async def rollback_memory(self, memory_id: str) -> None:
        await self.db.execute(
            "UPDATE memories SET active_state = 0, valid_to = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE memory_id = ?;",
            (memory_id,),
        )
        await self.append_audit("rollback_memory", memory_id, {})
