from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .migrations import MigrationManager
from .sqlite_async import AsyncSQLite


MEMORY_TYPES = {
    "FACT", "EXPERIENCE", "OBSERVATION", "OPINION", "PREFERENCE",
    "PROJECT", "TASK", "RELATION", "EPISODIC", "ENT_RELATION", "PERSONA",
    "OPINION_SHIFT", "LESSON",
}


@dataclass(slots=True)
class MemoryRecord:
    """P0 schema: memories.id PK, not memory_id."""
    id: str = field(default_factory=lambda: uuid4().hex)
    session_id: str | None = None
    memory_type: str = "FACT"
    content: str = ""
    content_summary: str | None = None
    content_hash: str = ""
    checksum: str = ""
    importance_score: float = 0.0
    confidence_score: float = 0.0
    decay_score: float = 0.0
    recency_score: float = 0.0
    access_count: int = 0
    reinforcement_score: float = 0.0
    safety_score: float = 1.0
    active_state: str = "active"
    superseded_by: str | None = None
    contradiction_group_id: str | None = None
    valid_from: str = ""
    valid_to: str | None = None
    archived_at: str | None = None
    metadata_json: str = "{}"


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

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_record(self, record: MemoryRecord) -> MemoryRecord:
        if record.memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unsupported memory_type: {record.memory_type}")
        if not record.id:
            record.id = uuid4().hex
        if not record.content_hash:
            record.content_hash = self.checksum(record.content)
        if not record.checksum:
            record.checksum = self.checksum(record.content)
        if not record.valid_from:
            record.valid_from = self._now_iso()
        if record.active_state not in ("active", "archived", "superseded", "quarantined"):
            record.active_state = "active"
        return record

    @staticmethod
    def _normalize_search_query(query: str) -> str:
        tokens = [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in query).split() if t]
        return " OR ".join(tokens) if tokens else ""

    async def store_memory(self, record: MemoryRecord) -> str:
        """Store one memory atomically using BEGIN IMMEDIATE via self.db.transaction(mode='IMMEDIATE').

        Atomic write set: memories + memory_versions + audit_logs.
        """
        n = self._normalize_record(record)

        async with self.db.transaction(mode="IMMEDIATE") as conn:
            conn.execute(
                """INSERT INTO memories (id,session_id,memory_type,content,content_summary,content_hash,checksum,
                importance_score,confidence_score,decay_score,recency_score,access_count,reinforcement_score,safety_score,
                active_state,superseded_by,contradiction_group_id,valid_from,valid_to,archived_at,created_at,updated_at,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'),?)
                ON CONFLICT(id) DO UPDATE SET content=excluded.content,content_hash=excluded.content_hash,
                checksum=excluded.checksum,importance_score=excluded.importance_score,confidence_score=excluded.confidence_score,
                decay_score=excluded.decay_score,recency_score=excluded.recency_score,access_count=excluded.access_count,
                reinforcement_score=excluded.reinforcement_score,safety_score=excluded.safety_score,
                active_state=excluded.active_state,superseded_by=excluded.superseded_by,
                contradiction_group_id=excluded.contradiction_group_id,valid_from=excluded.valid_from,
                valid_to=excluded.valid_to,archived_at=excluded.archived_at,updated_at=datetime('now'),
                metadata_json=excluded.metadata_json,content_summary=excluded.content_summary,
                session_id=excluded.session_id,memory_type=excluded.memory_type;""",
                (n.id,n.session_id,n.memory_type,n.content,n.content_summary,n.content_hash,n.checksum,
                 n.importance_score,n.confidence_score,n.decay_score,n.recency_score,n.access_count,
                 n.reinforcement_score,n.safety_score,n.active_state,n.superseded_by,n.contradiction_group_id,
                 n.valid_from,n.valid_to,n.archived_at,n.metadata_json))

            # Write memory_version
            cur = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM memory_versions WHERE memory_id=?;",(n.id,))
            next_ver = int(cur.fetchone()[0])
            now = self._now_iso()
            conn.execute(
                "INSERT INTO memory_versions(id,memory_id,version,content,content_hash,checksum,valid_from,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
                (uuid4().hex,n.id,next_ver,n.content,n.content_hash,n.checksum,n.valid_from or now,now,"{}"))

            # Write audit_log
            conn.execute(
                "INSERT INTO audit_logs(id,entity_type,entity_id,action,after_json,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?);",
                (uuid4().hex,"memories",n.id,"store_memory",
                 json.dumps({"memory_type":n.memory_type,"checksum":n.checksum}),
                 self.checksum(f"{n.id}:store_memory:{now}"),now,"{}"))

        return n.id

    async def store_memories(self, records: list[MemoryRecord]) -> int:
        if not records: return 0
        async with self.db.transaction():
            conn = self.db._require_conn()
            now = self._now_iso()
            for r in records:
                n = self._normalize_record(r)
                conn.execute("""INSERT INTO memories (id,session_id,memory_type,content,content_summary,content_hash,checksum,
                importance_score,confidence_score,decay_score,recency_score,access_count,reinforcement_score,safety_score,
                active_state,superseded_by,contradiction_group_id,valid_from,valid_to,archived_at,created_at,updated_at,metadata_json)
                VALUES (:id,:sid,:mt,:c,:cs,:ch,:ck,:is,:cf,:ds,:rs,:ac,:rf,:sf,:as,:sb,:cg,:vf,:vt,:aa,:now,:now,:mj)
                ON CONFLICT(id) DO UPDATE SET content=excluded.content,content_hash=excluded.content_hash,
                checksum=excluded.checksum,importance_score=excluded.importance_score,confidence_score=excluded.confidence_score,
                decay_score=excluded.decay_score,recency_score=excluded.recency_score,access_count=excluded.access_count,
                reinforcement_score=excluded.reinforcement_score,safety_score=excluded.safety_score,
                active_state=excluded.active_state,superseded_by=excluded.superseded_by,
                contradiction_group_id=excluded.contradiction_group_id,valid_from=excluded.valid_from,
                valid_to=excluded.valid_to,archived_at=excluded.archived_at,updated_at=:now,
                metadata_json=excluded.metadata_json,content_summary=excluded.content_summary,
                session_id=excluded.session_id,memory_type=excluded.memory_type;""",
                {"id":n.id,"sid":n.session_id,"mt":n.memory_type,"c":n.content,"cs":n.content_summary,
                 "ch":n.content_hash,"ck":n.checksum,"is":n.importance_score,"cf":n.confidence_score,
                 "ds":n.decay_score,"rs":n.recency_score,"ac":n.access_count,"rf":n.reinforcement_score,
                 "sf":n.safety_score,"as":n.active_state,"sb":n.superseded_by,"cg":n.contradiction_group_id,
                 "vf":n.valid_from,"vt":n.valid_to,"aa":n.archived_at,"mj":n.metadata_json,"now":now})
                ver = int(conn.execute("SELECT COALESCE(MAX(version),0) FROM memory_versions WHERE memory_id=?;",(n.id,)).fetchone()[0])+1
                conn.execute("INSERT INTO memory_versions(id,memory_id,version,content,content_hash,checksum,valid_from,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
                    (uuid4().hex,n.id,ver,n.content,n.content_hash,n.checksum,now,now,"{}"))
                conn.execute("INSERT INTO audit_logs(id,entity_type,entity_id,action,after_json,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?);",
                    (uuid4().hex,"memories",n.id,"store_memory",json.dumps({"memory_type":n.memory_type,"checksum":n.checksum}),n.checksum,now,"{}"))
        return len(records)

    async def write_version(self, memory_id: str, content: str, checksum_val: str) -> None:
        row = await self.db.fetchone("SELECT COALESCE(MAX(version),0) AS version FROM memory_versions WHERE memory_id=?;",(memory_id,))
        next_v = int(row["version"] if row else 0)+1
        now = self._now_iso()
        ch = self.checksum(content)
        await self.db.execute("INSERT INTO memory_versions(id,memory_id,version,content,content_hash,checksum,valid_from,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
            (uuid4().hex,memory_id,next_v,content,ch,checksum_val or ch,now,now,"{}"))

    async def get_memory(self, memory_id: str) -> dict[str,Any]|None:
        row = await self.db.fetchone("SELECT * FROM memories WHERE id=?;",(memory_id,))
        return dict(row) if row else None

    async def list_memories(self, limit: int=1000) -> list[dict[str,Any]]:
        rows = await self.db.fetchall("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?;",(limit,))
        return [dict(r) for r in rows]

    async def list_active_memories(self, limit: int=100) -> list[dict[str,Any]]:
        rows = await self.db.fetchall("SELECT * FROM memories WHERE active_state='active' ORDER BY importance_score DESC, updated_at DESC LIMIT ?;",(limit,))
        return [dict(r) for r in rows]

    async def search_full_text(self, query: str, limit: int=20) -> list[dict[str,Any]]:
        q = self._normalize_search_query(query)
        if not q: return []
        rows = await self.db.fetchall("SELECT m.* FROM memories m JOIN memories_fts f ON m.rowid=f.rowid WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?;",(q,limit))
        return [dict(r) for r in rows]

    async def record_access(self, memory_id: str) -> None:
        now = self._now_iso()
        await self.db.execute("UPDATE memories SET access_count=access_count+1, updated_at=? WHERE id=?;",(now,memory_id))
        await self.db.execute("INSERT INTO memory_access_logs(id,memory_id,access_type,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?);",
            (uuid4().hex,memory_id,"read",self.checksum(f"access:{memory_id}:{now}"),now,"{}"))

    async def supersede_memory(self, memory_id: str, superseded_by: str) -> None:
        now = self._now_iso()
        await self.db.execute("UPDATE memories SET active_state='superseded',superseded_by=?,valid_to=?,updated_at=? WHERE id=?;",(superseded_by,now,now,memory_id))
        await self.append_audit("memories",memory_id,"supersede_memory",after_json={"superseded_by":superseded_by})

    async def add_conflict(self, memory_id: str, conflicting_memory_id: str, reason: str) -> None:
        now = self._now_iso()
        await self.db.execute("INSERT INTO memory_conflicts(id,memory_id,conflicting_memory_id,contradiction_reason,checksum,resolved_state,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?);",
            (uuid4().hex,memory_id,conflicting_memory_id,reason,self.checksum(f"{memory_id}:{conflicting_memory_id}:{reason}"),"open",now,"{}"))

    async def add_entity(self, name: str, entity_type: str="unknown", metadata_json: str="{}") -> str:
        eid = uuid4().hex; now = self._now_iso(); nn = name.lower().strip()
        await self.db.execute("INSERT INTO entities(id,name,entity_type,normalized_name,active_state,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?);",
            (eid,name,entity_type,nn,"active",self.checksum(f"{nn}:{entity_type}"),now,metadata_json))
        return eid

    async def add_relation(self, source_entity_id: str, target_entity_id: str, relation_type: str, confidence_score: float=1.0) -> str:
        rid = uuid4().hex; now = self._now_iso()
        await self.db.execute("INSERT INTO relations(id,source_entity_id,target_entity_id,relation_type,confidence_score,active_state,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
            (rid,source_entity_id,target_entity_id,relation_type,confidence_score,"active",self.checksum(f"{source_entity_id}:{target_entity_id}:{relation_type}"),now,"{}"))
        return rid

    async def add_session_summary(self, session_id: str, summary: str, source_count: int=0) -> None:
        now = self._now_iso(); ch = self.checksum(summary)
        await self.db.execute("INSERT INTO session_summaries(id,session_id,summary,content_hash,checksum,valid_from,active_state,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
            (uuid4().hex,session_id,summary,ch,ch,now,"active",now,"{}"))

    async def add_episodic_memory(self, memory_id: str, session_id: str|None=None, content: str="", summary: str|None=None, importance_score: float=0.5) -> str:
        eid = uuid4().hex; now = self._now_iso(); ch = self.checksum(content)
        await self.db.execute("INSERT INTO episodic_memories(id,memory_id,session_id,content,summary,importance_score,valid_from,active_state,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?);",
            (eid,memory_id,session_id,content,summary,importance_score,now,"active",ch,now,"{}"))
        return eid

    async def quarantine_memory(self, memory_id: str, reason: str) -> None:
        now = self._now_iso()
        await self.db.execute("INSERT INTO safety_quarantine(id,memory_id,reason,active_state,checksum,created_at,metadata_json) VALUES (?,?,?,?,?,?,?);",
            (uuid4().hex,memory_id,reason,"quarantined",self.checksum(f"quarantine:{memory_id}:{reason}"),now,"{}"))

    async def append_audit(self, entity_type: str, entity_id: str, action: str, before_json: dict|None=None, after_json: dict|None=None, actor: str|None=None) -> None:
        now = self._now_iso()
        await self.db.execute("INSERT INTO audit_logs(id,entity_type,entity_id,action,before_json,after_json,checksum,created_at,actor,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?);",
            (uuid4().hex,entity_type,entity_id,action,
             json.dumps(before_json) if before_json else None,
             json.dumps(after_json) if after_json else None,
             self.checksum(f"{entity_type}:{entity_id}:{action}:{now}"),now,actor,"{}"))

    async def replay_events(self, action: str|None=None, limit: int=100) -> list[dict[str,Any]]:
        if action:
            rows = await self.db.fetchall("SELECT * FROM audit_logs WHERE action=? ORDER BY created_at ASC LIMIT ?;",(action,limit))
        else:
            rows = await self.db.fetchall("SELECT * FROM audit_logs ORDER BY created_at ASC LIMIT ?;",(limit,))
        return [dict(r) for r in rows]

    async def export_markdown(self, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rows = await self.db.fetchall("SELECT * FROM memories ORDER BY updated_at DESC;")
        path = output_dir / "memories.md"
        lines = ["# Memories",""]
        for r in rows:
            item = dict(r)
            lines.append(f"- {item['id']} [{item['memory_type']}] {item['content']}")
        await asyncio.to_thread(path.write_text,"\n".join(lines)+"\n",encoding="utf-8")
        return [path]

    async def rollback_memory(self, memory_id: str) -> None:
        now = self._now_iso()
        await self.db.execute("UPDATE memories SET active_state='archived',valid_to=?,updated_at=? WHERE id=?;",(now,now,memory_id))
        await self.append_audit("memories",memory_id,"rollback_memory")

    async def update_memory_versioned(
        self, memory_id: str, changes: dict[str, Any], *, actor: str = "system", reason: str = ""
    ) -> str:
        """Version-preserving memory update. Writes version + audit atomically."""
        ALLOWED = {
            "content", "importance_score", "confidence_score", "decay_score",
            "recency_score", "active_state", "valid_from", "valid_to", "scope",
            "session_id", "entities_json", "tags_json", "metadata_json",
        }
        safe = {k: v for k, v in changes.items() if k in ALLOWED and k != "id"}
        if not safe:
            return memory_id

        async with self.db.transaction() as conn:
            if "content" in safe:
                safe["checksum"] = self.checksum(str(safe["content"]))
                safe["content_hash"] = safe["checksum"]
            safe["updated_at"] = self._now_iso()

            set_sql = ", ".join(f"{k}=?" for k in safe)
            conn.execute(f"UPDATE memories SET {set_sql} WHERE id=?;", (*safe.values(), memory_id))

            row = conn.execute("SELECT content, checksum FROM memories WHERE id=?;", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(f"memory not found: {memory_id}")
            content_val = row["content"]
            checksum_val = row["checksum"]

            cur = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM memory_versions WHERE memory_id=?;", (memory_id,))
            next_ver = int(cur.fetchone()[0])
            now = self._now_iso()
            conn.execute(
                "INSERT INTO memory_versions(id,memory_id,version,content,content_hash,checksum,valid_from,created_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?);",
                (uuid4().hex, memory_id, next_ver, content_val, checksum_val, checksum_val, now, now, "{}"),
            )

            conn.execute(
                "INSERT INTO audit_logs(id,entity_type,entity_id,action,before_json,after_json,checksum,created_at,actor,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?);",
                (uuid4().hex, "memories", memory_id, "update_versioned", None,
                 json.dumps({"changed": list(safe), "reason": reason}),
                 self.checksum(f"update:{memory_id}:{now}"), now, actor, "{}"),
            )

        return memory_id
