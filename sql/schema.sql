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
