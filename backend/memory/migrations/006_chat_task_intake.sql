-- Migration 006: Chat task intake (exact due instant + chat request idempotency)
-- Idempotent; mirrors the statements applied at startup by backend/memory/db.py.

-- 1. Exact due instant (UTC). tasks.due_date stays the user's local calendar day.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;

-- 2. Client request ids: a retried chat mutation returns the stored result instead of repeating it.
CREATE TABLE IF NOT EXISTS chat_request_log (
    owner_identity  TEXT         NOT NULL,
    request_id      TEXT         NOT NULL,
    state           TEXT         NOT NULL DEFAULT 'pending',
    response        JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_identity, request_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_request_log_created ON chat_request_log(created_at);
