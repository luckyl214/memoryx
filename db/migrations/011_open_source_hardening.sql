PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS lesson_triggers (
    lesson_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('intent', 'pattern', 'prohibited')),
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(lesson_id, trigger, trigger_type),
    FOREIGN KEY(lesson_id) REFERENCES lesson_memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lesson_triggers_lookup
ON lesson_triggers(trigger_type, trigger, active_state);

CREATE TABLE IF NOT EXISTS entity_memory_links (
    entity_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'mentioned',
    valid_from TEXT,
    valid_to TEXT,
    confidence_score REAL NOT NULL DEFAULT 0.5,
    active_state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(entity_id, memory_id, relation_type),
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entity_memory_links_timeline
ON entity_memory_links(entity_id, valid_from, valid_to, memory_id);

INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type)
SELECT lm.id, lower(value), 'intent'
FROM lesson_memories lm, json_each(lm.trigger_intents_json)
WHERE lm.active_state = 'active' AND value IS NOT NULL AND trim(value) <> '';

INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type)
SELECT lm.id, lower(value), 'pattern'
FROM lesson_memories lm, json_each(lm.trigger_patterns_json)
WHERE lm.active_state = 'active' AND value IS NOT NULL AND trim(value) <> '';

INSERT OR IGNORE INTO lesson_triggers(lesson_id, trigger, trigger_type)
SELECT lm.id, lower(value), 'prohibited'
FROM lesson_memories lm, json_each(lm.prohibited_patterns_json)
WHERE lm.active_state = 'active' AND value IS NOT NULL AND trim(value) <> '';

INSERT OR IGNORE INTO entity_memory_links(entity_id, memory_id, relation_type, confidence_score, valid_from)
SELECT me.entity_id, me.memory_id, COALESCE(me.role, 'mentioned'), me.confidence_score, m.valid_from
FROM memory_entities me
JOIN memories m ON m.id = me.memory_id;
