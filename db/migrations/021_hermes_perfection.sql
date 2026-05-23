PRAGMA foreign_keys=ON;

-- P12/P12.1: Hermes perfection + app-factory readiness + LLM safety audit tables.
-- Additive/repair migration only.

-- Clean bad generated index name from earlier migration and replace it with a stable name.
DROP INDEX IF EXISTS idx_taYOUR_API_KEY_HERE;

CREATE INDEX IF NOT EXISTS idx_task_durations_entity_time
ON task_durations(entity_id, start_time, end_time);

-- Conversation log FTS repair. Existing schema creates conversation_logs_fts
-- but did not install triggers in some releases.
CREATE TRIGGER IF NOT EXISTS conversation_logs_ai AFTER INSERT ON conversation_logs BEGIN
    INSERT INTO conversation_logs_fts(rowid, content, role)
    VALUES (new.rowid, new.content, new.role);
END;

CREATE TRIGGER IF NOT EXISTS conversation_logs_ad AFTER DELETE ON conversation_logs BEGIN
    INSERT INTO conversation_logs_fts(conversation_logs_fts, rowid, content, role)
    VALUES('delete', old.rowid, old.content, old.role);
END;

CREATE TRIGGER IF NOT EXISTS conversation_logs_au AFTER UPDATE ON conversation_logs BEGIN
    INSERT INTO conversation_logs_fts(conversation_logs_fts, rowid, content, role)
    VALUES('delete', old.rowid, old.content, old.role);
    INSERT INTO conversation_logs_fts(rowid, content, role)
    VALUES (new.rowid, new.content, new.role);
END;

INSERT INTO conversation_logs_fts(rowid, content, role)
SELECT c.rowid, c.content, c.role
FROM conversation_logs c
WHERE NOT EXISTS (
    SELECT 1 FROM conversation_logs_fts f WHERE f.rowid = c.rowid
);

-- LLM safety decisions are first-class audit events. They are separate from
-- hallucination_events because they cover prompt injection, tool abuse, and
-- untrusted tool output handling.
CREATE TABLE IF NOT EXISTS llm_safety_events (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    surface TEXT NOT NULL, -- user_input | tool_call | tool_output | assistant_output | memory_context
    decision TEXT NOT NULL, -- allow | warn | block | require_confirmation | require_dry_run | require_tool_verification
    severity TEXT NOT NULL DEFAULT 'low',
    input_hash TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    flags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_llm_safety_session_time
ON llm_safety_events(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_safety_surface_decision
ON llm_safety_events(surface, decision, created_at DESC);
