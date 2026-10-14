-- Real labeled set: de-identified examples built from reviewed corrections. Safe to run more than once.
-- Run in the Supabase SQL editor. Row level security on, with no policies, so only the app (direct
-- database connection) can read it. There is deliberately no link to the message, sender, or time of day.

CREATE TABLE IF NOT EXISTS real_labeled_set (
    id BIGSERIAL PRIMARY KEY,
    text_deid TEXT NOT NULL,
    text_hash TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    residual TEXT NOT NULL DEFAULT '',
    created_week TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    expires_at TEXT NOT NULL
);

ALTER TABLE real_labeled_set ENABLE ROW LEVEL SECURITY;
