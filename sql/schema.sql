-- Run once in the Supabase SQL editor. Tables hold gifter messages, so row level security is turned
-- on with no policies: Supabase's public API cannot read them. The app connects with the database
-- URL (the postgres role), which is not affected by row level security.

CREATE TABLE IF NOT EXISTS raw_payloads (
    id BIGSERIAL PRIMARY KEY,
    received_at TEXT NOT NULL,
    signature_ok INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    wamid TEXT NOT NULL UNIQUE,
    wa_from TEXT NOT NULL,
    profile_name TEXT,
    group_id TEXT,
    msg_type TEXT NOT NULL,
    text TEXT,
    sent_at TEXT,
    received_at TEXT NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw_payloads(id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL UNIQUE REFERENCES messages(id),
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);

ALTER TABLE raw_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

-- Phase 3 additions
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
