-- Phase 4 migration for an existing Supabase database. Safe to run more than once.
-- Run in the Supabase SQL editor. Row level security on, with no policies, as for the other tables.

CREATE TABLE IF NOT EXISTS replies (
    id BIGSERIAL PRIMARY KEY,
    wa_from TEXT NOT NULL,
    replied_at TEXT NOT NULL,
    marked_by TEXT
);
CREATE INDEX IF NOT EXISTS replies_sender ON replies (wa_from, replied_at);

CREATE TABLE IF NOT EXISTS corrections (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL UNIQUE REFERENCES messages(id),
    original_category TEXT,
    original_priority TEXT,
    corrected_category TEXT NOT NULL,
    corrected_priority TEXT NOT NULL,
    note TEXT,
    corrected_by TEXT,
    corrected_at TEXT NOT NULL,
    exported_at TEXT
);

ALTER TABLE replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE corrections ENABLE ROW LEVEL SECURITY;
