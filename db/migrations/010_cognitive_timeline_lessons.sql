PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS memory_feedback_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    session_id TEXT,
    positive INTEGER NOT NULL CHECK (positive IN (0, 1)),
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user',
    old_confidence REAL,
    new_confidence REAL,
    old_reinforcement REAL,
    new_reinforcement REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_similarity_edges (
    source_memory_id TEXT NOT NULL,
    target_memory_id TEXT NOT NULL,
    semantic_similarity REAL NOT NULL DEFAULT 0.0,
    keyword_similarity REAL NOT NULL DEFAULT 0.0,
    entity_overlap REAL NOT NULL DEFAULT 0.0,
    graph_distance INTEGER,
    combined_score REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(source_memory_id, target_memory_id),
    FOREIGN KEY(source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(target_memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_propagations (
    id TEXT PRIMARY KEY,
    feedback_event_id TEXT NOT NULL,
    from_memory_id TEXT NOT NULL,
    to_memory_id TEXT NOT NULL,
    propagation_score REAL NOT NULL,
    confidence_delta REAL NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(feedback_event_id) REFERENCES memory_feedback_events(id) ON DELETE CASCADE,
    FOREIGN KEY(from_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(to_memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lesson_memories (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL UNIQUE,
    lesson_text TEXT NOT NULL,
    policy_type TEXT NOT NULL DEFAULT 'warn',
    severity REAL NOT NULL DEFAULT 0.5,
    trigger_intents_json TEXT NOT NULL DEFAULT '[]',
    trigger_patterns_json TEXT NOT NULL DEFAULT '[]',
    prohibited_patterns_json TEXT NOT NULL DEFAULT '[]',
    recommended_action TEXT NOT NULL DEFAULT '',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    confidence_score REAL NOT NULL DEFAULT 0.5,
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lesson_evidence (
    lesson_id TEXT NOT NULL,
    evidence_memory_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL DEFAULT 'feedback',
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(lesson_id, evidence_memory_id, evidence_type),
    FOREIGN KEY(lesson_id) REFERENCES lesson_memories(id) ON DELETE CASCADE,
    FOREIGN KEY(evidence_memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT,
    entity_id TEXT,
    title TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'generic',
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    confidence_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS task_durations (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    session_id TEXT,
    entity_id TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'event',
    confidence_score REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'mentioned',
    confidence_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(memory_id, entity_id, role),
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opinion_observations (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    stance_score REAL NOT NULL,
    sentiment_score REAL NOT NULL DEFAULT 0.0,
    aspect TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    evidence_text TEXT NOT NULL DEFAULT '',
    confidence_score REAL NOT NULL DEFAULT 0.5,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opinion_shifts (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL UNIQUE,
    entity_id TEXT NOT NULL,
    from_time TEXT NOT NULL,
    to_time TEXT NOT NULL,
    before_score REAL NOT NULL,
    after_score REAL NOT NULL,
    delta REAL NOT NULL,
    before_summary TEXT NOT NULL,
    after_summary TEXT NOT NULL,
    possible_causes_json TEXT NOT NULL DEFAULT '[]',
    evidence_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retrieval_weight_overrides (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    session_id TEXT,
    intent TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    weights_json TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS self_edit_plans (
    plan_id TEXT PRIMARY KEY,
    source_reflection_id TEXT,
    session_id TEXT,
    status TEXT NOT NULL DEFAULT 'preview',
    request_json TEXT NOT NULL,
    preview_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_feedback_memory_created
ON memory_feedback_events(memory_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_similarity_source_score
ON memory_similarity_edges(source_memory_id, combined_score DESC);

CREATE INDEX IF NOT EXISTS idx_lesson_active_severity
ON lesson_memories(active_state, severity DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_durations_entity_time
ON task_durations(entity_id, start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_tasks_session_status
ON tasks(session_id, status, start_time);

CREATE INDEX IF NOT EXISTS idx_memory_entities_entity
ON memory_entities(entity_id, memory_id);

CREATE INDEX IF NOT EXISTS idx_opinion_obs_entity_time
ON opinion_observations(entity_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_opinion_shift_entity_time
ON opinion_shifts(entity_id, from_time, to_time);

CREATE INDEX IF NOT EXISTS idx_weight_overrides_lookup
ON retrieval_weight_overrides(active_state, scope, intent, priority DESC);
