-- =============================================================================
-- Migration 050: Trust, Conflict & Forgetting
-- Adds column-based trust metadata, provenance tracking, conflict detection,
-- and forgetting event logging for the MemoryX cognitive layer.
-- =============================================================================

-- ── memories table new columns ──
-- Applied via Python migration runner using PRAGMA table_info() checks
-- since SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS.

-- See tools/memoryx_p151_migrate.py for the safe column adder.

-- source_type: user_explicit, tool_verified, system_event, conversation_log,
--               agent_inferred, agent_reflection, unknown
-- ALTER TABLE memories ADD COLUMN source_type TEXT DEFAULT 'unknown';

-- verification_status: unverified, verified, contradicted, user_rejected
-- ALTER TABLE memories ADD COLUMN verification_status TEXT DEFAULT 'unverified';

-- expires_at: ISO 8601 timestamp when this memory naturally expires
-- ALTER TABLE memories ADD COLUMN expires_at TEXT;

-- last_verified_at: timestamp of last verification
-- ALTER TABLE memories ADD COLUMN last_verified_at TEXT;

-- trust_score: composite confidence (0.0–1.0) derived from source_type,
--              verification_status, confidence_score, importance_score
-- ALTER TABLE memories ADD COLUMN trust_score REAL DEFAULT 0.5;

-- ── memory_provenance: tracks where each memory came from ──
CREATE TABLE IF NOT EXISTS memory_provenance (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_provenance_memory
ON memory_provenance(memory_id);

CREATE INDEX IF NOT EXISTS idx_memory_provenance_source
ON memory_provenance(source_type, created_at);

-- ── memory_conflicts: detected semantic contradictions ──
CREATE TABLE IF NOT EXISTS memory_conflicts (
    id TEXT PRIMARY KEY,
    memory_a_id TEXT NOT NULL,
    memory_b_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    resolved_state TEXT NOT NULL DEFAULT 'open',
    confidence REAL NOT NULL DEFAULT 0.5,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_conflicts_status
ON memory_conflicts(resolved_state, created_at);

-- ── memory_forgetting_events: audit trail for archiving and decay ──
CREATE TABLE IF NOT EXISTS memory_forgetting_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    old_confidence REAL,
    new_confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_forgetting_memory
ON memory_forgetting_events(memory_id, created_at);