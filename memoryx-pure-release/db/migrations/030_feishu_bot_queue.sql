-- db/migrations/030_feishu_bot_queue.sql
-- P14 Feishu UX Adapter: 飞书消息队列表

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS feishu_jobs (
    job_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT,
    message_id TEXT,
    card_message_id TEXT,
    state TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feishu_jobs_state_priority
ON feishu_jobs(state, priority, created_at);

CREATE TABLE IF NOT EXISTS feishu_attachments (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    file_key TEXT,
    image_key TEXT,
    name TEXT,
    mime_type TEXT,
    size INTEGER,
    local_path TEXT,
    source_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(job_id) REFERENCES feishu_jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feishu_attachments_job
ON feishu_attachments(job_id, status);
