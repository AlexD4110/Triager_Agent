-- Phase 3 migration for an existing Supabase database. Safe to run more than once.
-- Run in the Supabase SQL editor. Same row level security rule as before: on, with no policies.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS updated_at TEXT;

CREATE TABLE IF NOT EXISTS gifters (
    wa_id TEXT PRIMARY KEY,
    name TEXT,
    tier TEXT NOT NULL DEFAULT 'standard',
    hosts TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS live_status (
    host TEXT PRIMARY KEY,
    is_live INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS triage_results (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL UNIQUE REFERENCES messages(id),
    category TEXT,
    safety_flag INTEGER NOT NULL DEFAULT 0,
    security_flag INTEGER NOT NULL DEFAULT 0,
    churn_signal INTEGER NOT NULL DEFAULT 0,
    mentions_host TEXT,
    language TEXT,
    summary TEXT,
    confidence DOUBLE PRECISION,
    fallback TEXT,
    priority TEXT NOT NULL,
    deadline_minutes INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    alert_status TEXT NOT NULL DEFAULT 'none',
    alert_attempts INTEGER NOT NULL DEFAULT 0,
    alert_error TEXT
);

ALTER TABLE gifters ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_results ENABLE ROW LEVEL SECURITY;
