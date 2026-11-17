-- Migration 007: persisted answer truncation state on chat messages
-- Idempotent and additive; mirrors the statements applied at startup by backend/memory/db.py.

-- is_truncated: the stored assistant text was cut short (token limit) or interrupted (connection dropped).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_truncated BOOLEAN NOT NULL DEFAULT FALSE;
-- stream_status: NULL (complete), 'truncated' (ended on the token limit) or 'interrupted' (stream dropped).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS stream_status TEXT;
