PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS claim_verification_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    question TEXT NOT NULL DEFAULT '',
    answer_hash TEXT NOT NULL,
    claim_count INTEGER NOT NULL DEFAULT 0,
    supported_count INTEGER NOT NULL DEFAULT 0,
    contradicted_count INTEGER NOT NULL DEFAULT 0,
    unsupported_count INTEGER NOT NULL DEFAULT 0,
    risk_score REAL NOT NULL DEFAULT 0.0,
    action TEXT NOT NULL DEFAULT 'allow',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    session_id TEXT,
    response_id TEXT,
    claim_text TEXT NOT NULL,
    normalized_claim TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'fact',
    source TEXT NOT NULL DEFAULT 'assistant',
    confidence_score REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'unverified',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES claim_verification_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    memory_id TEXT,
    evidence_text TEXT NOT NULL,
    verdict TEXT NOT NULL DEFAULT 'unknown',
    support_score REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'memoryx',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS hallucination_events (
    id TEXT PRIMARY KEY,
    claim_id TEXT,
    session_id TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    reason TEXT NOT NULL,
    lesson_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE SET NULL,
    FOREIGN KEY(lesson_id) REFERENCES lesson_memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS lesson_enforcement_events (
    id TEXT PRIMARY KEY,
    lesson_id TEXT,
    session_id TEXT,
    action_text TEXT NOT NULL,
    policy_level TEXT NOT NULL DEFAULT 'warn',
    decision TEXT NOT NULL DEFAULT 'allow',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(lesson_id) REFERENCES lesson_memories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS narrative_reflections (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    entity_id TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    reflection_type TEXT NOT NULL DEFAULT 'periodic',
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS recurring_error_patterns (
    id TEXT PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,
    pattern_text TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    lesson_id TEXT,
    severity REAL NOT NULL DEFAULT 0.5,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active_state TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(lesson_id) REFERENCES lesson_memories(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_claim_runs_session_time ON claim_verification_runs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claims_status_time ON claims(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON claim_evidence(claim_id, verdict, support_score DESC);
CREATE INDEX IF NOT EXISTS idx_hallucination_session_time ON hallucination_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lesson_enforcement_session_time ON lesson_enforcement_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_narrative_window ON narrative_reflections(reflection_type, window_start, window_end);
CREATE INDEX IF NOT EXISTS idx_narrative_entity_time ON narrative_reflections(entity_id, window_start, window_end);
CREATE INDEX IF NOT EXISTS idx_recurring_error_active ON recurring_error_patterns(active_state, occurrences DESC, last_seen_at DESC);
