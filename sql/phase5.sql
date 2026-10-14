-- Phase 5 migration: record of deletion requests (a keyed hash of the sender, never the number itself).
-- Safe to run more than once. Row level security on, with no policies, as for the other tables.

CREATE TABLE IF NOT EXISTS deletion_log (
    id BIGSERIAL PRIMARY KEY,
    sender_hash TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    messages_affected INTEGER NOT NULL
);

ALTER TABLE deletion_log ENABLE ROW LEVEL SECURITY;
