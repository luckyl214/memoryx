PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    content_summary TEXT,
    content_hash TEXT NOT NULL,
    checksum TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.0,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    decay_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    active_state TEXT NOT NULL DEFAULT 'active',
    superseded_by TEXT,
    contradiction_group_id TEXT,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (superseded_by) REFERENCES memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    checksum TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(memory_id, version)
);

CREATE TABLE IF NOT EXISTS memory_conflicts (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    conflicting_memory_id TEXT NOT NULL,
    contradiction_reason TEXT NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    checksum TEXT NOT NULL,
    safety_score REAL NOT NULL DEFAULT 1.0,
    resolved_state TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (conflicting_memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS archived_memories (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    archived_reason TEXT NOT NULL,
    archived_at TEXT NOT NULL DEFAULT (datetime('now')),
    checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS episodic_memories (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    episode_index INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    summary TEXT,
    importance_score REAL NOT NULL DEFAULT 0.0,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    decay_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reflection_summaries (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    checksum TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.0,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    decay_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    checksum TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.0,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    decay_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(normalized_name, entity_type)
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (source_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_access_logs (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    access_type TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 1,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reinforcement_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    event_type TEXT NOT NULL,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS safety_quarantine (
    id TEXT PRIMARY KEY,
    memory_id TEXT,
    reason TEXT NOT NULL,
    safety_score REAL NOT NULL DEFAULT 0.0,
    active_state TEXT NOT NULL DEFAULT 'quarantined',
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    content,
    content_summary,
    content='memories',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, memory_id, content, content_summary)
    VALUES (new.rowid, new.id, new.content, coalesce(new.content_summary, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, memory_id, content, content_summary)
    VALUES('delete', old.rowid, old.id, old.content, coalesce(old.content_summary, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, memory_id, content, content_summary)
    VALUES('delete', old.rowid, old.id, old.content, coalesce(old.content_summary, ''));
    INSERT INTO memories_fts(rowid, memory_id, content, content_summary)
    VALUES (new.rowid, new.id, new.content, coalesce(new.content_summary, ''));
END;

-- =============================================================================
-- Palace of Memory (记忆宫殿)
-- =============================================================================

CREATE TABLE IF NOT EXISTS palace_wings (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    wing_type TEXT NOT NULL DEFAULT 'general',
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS palace_rooms (
    id TEXT PRIMARY KEY,
    wing_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    room_type TEXT NOT NULL DEFAULT 'general',
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(wing_id) REFERENCES palace_wings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS palace_drawers (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(room_id) REFERENCES palace_rooms(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS palace_tunnels (
    id TEXT PRIMARY KEY,
    source_room_id TEXT NOT NULL,
    target_room_id TEXT NOT NULL,
    tunnel_type TEXT NOT NULL DEFAULT 'association',
    label TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 1.0,
    active_state TEXT NOT NULL DEFAULT 'active',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(source_room_id) REFERENCES palace_rooms(id) ON DELETE CASCADE,
    FOREIGN KEY(target_room_id) REFERENCES palace_rooms(id) ON DELETE CASCADE
);

-- =============================================================================
-- Conversation Logs (会话日志)
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversation_logs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    turn_index INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_logs_fts USING fts5(
    content,
    role,
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_palace_wing_active
ON palace_wings(active_state, name);

CREATE INDEX IF NOT EXISTS idx_palace_rooms_wing
ON palace_rooms(wing_id, active_state);

CREATE INDEX IF NOT EXISTS idx_palace_drawers_room
ON palace_drawers(room_id, active_state);

CREATE INDEX IF NOT EXISTS idx_palace_tunnels_source
ON palace_tunnels(source_room_id, active_state);

CREATE INDEX IF NOT EXISTS idx_conversation_logs_session
ON conversation_logs(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_memories_session_active ON memories(session_id, active_state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_scope_active ON memories(scope, active_state, updated_at DESC);
