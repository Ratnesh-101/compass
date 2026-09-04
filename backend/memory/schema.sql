-- Compass: Personal AI Assistant
-- Database schema — PostgreSQL + pgvector
-- Run: psql -d compass -f schema.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Trigger function: auto-update updated_at on row modification
-- ============================================================
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Projects — normalized registry (FK target for tasks & chunks)
-- ============================================================
CREATE TABLE projects (
    id          SERIAL       PRIMARY KEY,
    name        TEXT         NOT NULL UNIQUE,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================
-- Tasks — structured task / deadline store
-- ============================================================
CREATE TABLE tasks (
    id          SERIAL       PRIMARY KEY,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    project_id  INTEGER      REFERENCES projects(id) ON DELETE SET NULL,
    title       TEXT         NOT NULL,
    due_date    DATE,
    status      TEXT         NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open','in_progress','done','overdue')),
    priority    TEXT         DEFAULT 'medium'
                             CHECK (priority IN ('low','medium','high','urgent')),
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TRIGGER update_tasks_modtime
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();

CREATE INDEX idx_tasks_domain     ON tasks(domain);
CREATE INDEX idx_tasks_status     ON tasks(status);
CREATE INDEX idx_tasks_due_date   ON tasks(due_date);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);

-- ============================================================
-- Memory Chunks — vector store for semantic search
--
-- NOTE: The VECTOR dimension (768) matches the EMBEDDING_DIMENSION
-- setting in config.py. Qwen/Qwen3-Embedding-8B supports Matryoshka
-- dimension truncation (dimensions=768), keeping vectors within
-- pgvector's 2,000-dimension HNSW index ceiling.
--
-- Using HNSW index instead of IVFFlat because:
--   - IVFFlat requires a training step (needs existing rows to build lists)
--   - HNSW works immediately on empty tables and has better recall
-- ============================================================
CREATE TABLE memory_chunks (
    id          SERIAL       PRIMARY KEY,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    project_id  INTEGER      REFERENCES projects(id) ON DELETE SET NULL,
    content     TEXT         NOT NULL,
    embedding   VECTOR(768),
    source      TEXT,        -- e.g. repo URL, course name, file path
    tags        TEXT[],
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_memory_chunks_embedding   ON memory_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_memory_chunks_domain      ON memory_chunks(domain);
CREATE INDEX idx_memory_chunks_project_id  ON memory_chunks(project_id);
CREATE INDEX idx_memory_chunks_tags        ON memory_chunks USING gin(tags);

-- ============================================================
-- Conversations — chat sessions
-- ============================================================
CREATE TABLE conversations (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================
-- Messages — individual messages within a conversation
-- ============================================================
CREATE TABLE messages (
    id              SERIAL       PRIMARY KEY,
    conversation_id UUID         NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT         NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT         NOT NULL,
    skill_called    TEXT,        -- which skill was invoked, null for user messages
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conv_created ON messages(conversation_id, created_at);

-- ============================================================
-- Usage Log — token consumption & cost tracking
-- ============================================================
CREATE TABLE usage_log (
    id                 SERIAL        PRIMARY KEY,
    model              TEXT          NOT NULL,
    input_tokens       INTEGER       NOT NULL DEFAULT 0,
    output_tokens      INTEGER       NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(10,6),
    skill              TEXT,         -- which skill triggered this call
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_usage_log_model      ON usage_log(model);
CREATE INDEX idx_usage_log_created_at ON usage_log(created_at);
