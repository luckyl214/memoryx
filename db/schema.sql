PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    confidence_score REAL NOT NULL DEFAULT 0.5,
    decay_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL,
    superseded_by TEXT,
    valid_from TEXT,
    valid_to TEXT,
    active_state INTEGER NOT NULL DEFAULT 1,
    reinforcement_score REAL NOT NULL DEFAULT 0.0,
    safety_score REAL NOT NULL DEFAULT 1.0,
    scope TEXT NOT NULL DEFAULT 'global',
    source_message_id TEXT,
    entities_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT 'session',
    layer TEXT NOT NULL DEFAULT 'working',
    source TEXT NOT NULL DEFAULT 'dialogue',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (memory_type IN ('FACT','EXPERIENCE','OBSERVATION','OPINION','PREFERENCE','PROJECT','TASK','RELATION','EPISODIC','PERSONA','ENT_RELATION'))
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    embedding_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    dimension INTEGER NOT NULL,
    model_name TEXT,
    freshness_score REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relations (
    relation_id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_summaries (
    summary_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_versions (
    version_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_conflicts (
    conflict_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    conflicting_memory_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE,
    FOREIGN KEY(conflicting_memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS archived_memories (
    archive_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    content TEXT NOT NULL,
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT NOT NULL DEFAULT 'consolidated'
);

CREATE TABLE IF NOT EXISTS episodic_memories (
    episodic_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reflection_summaries (
    reflection_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_access_logs (
    access_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    access_type TEXT NOT NULL DEFAULT 'read',
    FOREIGN KEY(memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reinforcement_events (
    reinforcement_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    reinforcement_type TEXT NOT NULL,
    score_delta REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS safety_quarantine (
    quarantine_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'quarantined',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_logs (
    log_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    content
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(memory_id, content) VALUES (new.memory_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.memory_id;
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.memory_id;
    INSERT INTO memories_fts(memory_id, content) VALUES (new.memory_id, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_memories_active_importance ON memories(active_state, importance_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type_scope ON memories(memory_type, scope);
CREATE INDEX IF NOT EXISTS idx_memories_checksum ON memories(checksum);
CREATE INDEX IF NOT EXISTS idx_memories_valid_from ON memories(valid_from);
CREATE INDEX IF NOT EXISTS idx_memories_valid_to ON memories(valid_to);
CREATE INDEX IF NOT EXISTS idx_entities_name_type ON entities(entity_name, entity_type);
CREATE INDEX IF NOT EXISTS idx_relations_source_target ON relations(source_entity_id, target_entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_subject_created ON audit_logs(subject_id, created_at);
CREATE INDEX IF NOT EXISTS idx_access_memory_created ON memory_access_logs(memory_id, accessed_at);
CREATE INDEX IF NOT EXISTS idx_reinforcement_memory_created ON reinforcement_events(memory_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_session_created ON conversation_logs(session_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_logs_fts USING fts5(
    log_id UNINDEXED,
    content
);

CREATE TRIGGER IF NOT EXISTS conversation_logs_ai AFTER INSERT ON conversation_logs BEGIN
    INSERT INTO conversation_logs_fts(log_id, content) VALUES (new.log_id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS conversation_logs_ad AFTER DELETE ON conversation_logs BEGIN
    DELETE FROM conversation_logs_fts WHERE log_id = old.log_id;
END;
CREATE TRIGGER IF NOT EXISTS conversation_logs_au AFTER UPDATE ON conversation_logs BEGIN
    DELETE FROM conversation_logs_fts WHERE log_id = old.log_id;
    INSERT INTO conversation_logs_fts(log_id, content) VALUES (new.log_id, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_quarantine_status_created ON safety_quarantine(status, created_at);

-- Palace: 层次化可导航存储 (Wing → Room → Drawer)
CREATE TABLE IF NOT EXISTS palace_wings (
    wing_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS palace_rooms (
    room_id TEXT PRIMARY KEY,
    wing_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(wing_id) REFERENCES palace_wings(wing_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS palace_drawers (
    drawer_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    memory_id TEXT,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'conversation',
    line_start INTEGER DEFAULT 0,
    line_end INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(room_id) REFERENCES palace_rooms(room_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS palace_tunnels (
    tunnel_id TEXT PRIMARY KEY,
    source_wing_id TEXT NOT NULL,
    target_wing_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_wing_id) REFERENCES palace_wings(wing_id) ON DELETE CASCADE,
    FOREIGN KEY(target_wing_id) REFERENCES palace_wings(wing_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_palace_rooms_wing ON palace_rooms(wing_id);
CREATE INDEX IF NOT EXISTS idx_palace_drawers_room ON palace_drawers(room_id);
CREATE INDEX IF NOT EXISTS idx_palace_drawers_memory ON palace_drawers(memory_id);
