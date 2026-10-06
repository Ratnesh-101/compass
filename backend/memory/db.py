"""
Compass — Async database connection pool.

Uses asyncpg with pgvector codec registration.
The pool registers the vector type on every new connection via the `init` callback,
so all connections in the pool can read/write VECTOR columns.
"""
from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector


_pool: asyncpg.Pool | None = None
_tables_ensured: bool = False


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Called for every new connection in the pool.
    Registers the pgvector type codec so asyncpg can handle VECTOR columns."""
    await register_vector(conn)


async def _ensure_tables(pool: asyncpg.Pool) -> None:
    """Create agent_runs and agent_audit_log tables if they don't already exist."""
    async with pool.acquire(timeout=5.0) as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id                 TEXT          PRIMARY KEY,
            goal               TEXT          NOT NULL,
            status             TEXT          NOT NULL,
            accumulated_steps  JSONB         NOT NULL DEFAULT '[]'::jsonb,
            messages           JSONB         NOT NULL DEFAULT '[]'::jsonb,
            pending_actions    JSONB         NOT NULL DEFAULT '[]'::jsonb,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS conversation_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status          ON agent_runs(status);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at      ON agent_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id ON agent_runs(conversation_id);

        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id TEXT;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS guest_id TEXT;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS imported_from_id UUID;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_conversations_last_active ON conversations(last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conversations_guest_id ON conversations(guest_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_imported_from ON conversations(imported_from_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_is_shared ON conversations(is_shared);

        CREATE TABLE IF NOT EXISTS guest_migration_log (
            id                      SERIAL        PRIMARY KEY,
            guest_id                TEXT          NOT NULL,
            user_id                 TEXT          NOT NULL,
            guest_conversation_id   UUID          NOT NULL,
            user_conversation_id    UUID          NOT NULL,
            imported_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(guest_conversation_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_guest_mig_guest ON guest_migration_log(guest_id);
        CREATE INDEX IF NOT EXISTS idx_guest_mig_user ON guest_migration_log(user_id);

        CREATE TABLE IF NOT EXISTS agent_audit_log (
            id                 SERIAL        PRIMARY KEY,
            run_id             TEXT,
            tool               TEXT          NOT NULL,
            args               JSONB         NOT NULL DEFAULT '{}'::jsonb,
            affected_table     TEXT          NOT NULL DEFAULT 'tasks',
            affected_id        INTEGER,
            previous_state     JSONB,
            new_state          JSONB,
            approved_by        TEXT          NOT NULL DEFAULT 'user',
            status             TEXT          NOT NULL DEFAULT 'executed',
            is_reverted        BOOLEAN       NOT NULL DEFAULT FALSE,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE agent_audit_log DROP CONSTRAINT IF EXISTS agent_audit_log_run_id_fkey;
        ALTER TABLE agent_audit_log ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'executed';
        ALTER TABLE agent_audit_log ADD COLUMN IF NOT EXISTS is_reverted BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_agent_audit_log_run_id     ON agent_audit_log(run_id);
        CREATE INDEX IF NOT EXISTS idx_agent_audit_log_created_at ON agent_audit_log(created_at);

        CREATE TABLE IF NOT EXISTS tavily_usage_log (
            id         SERIAL       PRIMARY KEY,
            operation  TEXT         NOT NULL,
            credits    INTEGER      NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_tavily_usage_created_at ON tavily_usage_log(created_at);

        -- Dynamic Scheduling & Calendar Extensions
        ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_domain_check;
        ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_domain_check;
        ALTER TABLE memory_chunks DROP CONSTRAINT IF EXISTS memory_chunks_domain_check;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id VARCHAR(255) DEFAULT 'default_user';
        CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
        ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS user_id VARCHAR(255) DEFAULT 'default_user';
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_user_id ON memory_chunks(user_id);
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 60;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_end TIMESTAMPTZ;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_fixed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_rule TEXT;
        CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_start ON tasks(scheduled_start);

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash        TEXT          PRIMARY KEY,
                user_id           TEXT          NOT NULL,
                oauth_verified    BOOLEAN       NOT NULL DEFAULT FALSE,
                created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
                last_accessed_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
                expires_at        TIMESTAMPTZ   NOT NULL,
                revoked_at        TIMESTAMPTZ   DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_revoked_at ON sessions(revoked_at);

            CREATE TABLE IF NOT EXISTS calendar_connections (
                id                 SERIAL        PRIMARY KEY,
                user_id            TEXT          NOT NULL DEFAULT 'default_user',
                provider           TEXT          NOT NULL DEFAULT 'google',
                account_email      TEXT,
                refresh_token      TEXT,
                access_token       TEXT,
                token_expiry       TIMESTAMPTZ,
                scopes             TEXT[]        DEFAULT '{}',
                connected_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
                last_synced_at     TIMESTAMPTZ,
                sync_token         TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_conn_user_provider ON calendar_connections(user_id, provider);

        CREATE TABLE IF NOT EXISTS calendar_event_links (
            id                 SERIAL        PRIMARY KEY,
            task_id            INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            google_event_id    TEXT          NOT NULL,
            calendar_id        TEXT          NOT NULL DEFAULT 'primary',
            sync_status        TEXT          NOT NULL DEFAULT 'synced',
            last_synced_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(task_id, google_event_id)
        );

        CREATE TABLE IF NOT EXISTS scheduling_preferences (
            id                 SERIAL        PRIMARY KEY,
            user_id            TEXT          NOT NULL DEFAULT 'default_user' UNIQUE,
            work_start_time    TIME          NOT NULL DEFAULT '09:00:00',
            work_end_time      TIME          NOT NULL DEFAULT '18:00:00',
            work_days          INTEGER[]     NOT NULL DEFAULT '{1,2,3,4,5}',
            buffer_minutes     INTEGER       NOT NULL DEFAULT 15,
            preferred_focus    TEXT          NOT NULL DEFAULT 'morning'
        );

        CREATE TABLE IF NOT EXISTS task_dependencies (
            id                 SERIAL        PRIMARY KEY,
            task_id            INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            depends_on_task_id INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(task_id, depends_on_task_id),
            CHECK(task_id != depends_on_task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_dep_task_id ON task_dependencies(task_id);
        CREATE INDEX IF NOT EXISTS idx_task_dep_depends_on ON task_dependencies(depends_on_task_id);

        -- Shared DB Rate Limiter Table
        CREATE TABLE IF NOT EXISTS rate_limit_buckets (
            key          TEXT PRIMARY KEY,
            tokens       DOUBLE PRECISION NOT NULL,
            last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limit_updated ON rate_limit_buckets(last_updated);

        -- DB-Backed Single-Use Pending Actions for Agent Confirm & Undo
        CREATE TABLE IF NOT EXISTS pending_actions (
            action_id      TEXT PRIMARY KEY,
            run_id         TEXT NOT NULL,
            owner_identity TEXT NOT NULL,
            tool           TEXT NOT NULL,
            args_hash      TEXT NOT NULL,
            original_args  JSONB NOT NULL DEFAULT '{}'::jsonb,
            status         TEXT NOT NULL DEFAULT 'pending',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at     TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pending_actions_run ON pending_actions(run_id);
        CREATE INDEX IF NOT EXISTS idx_pending_actions_owner ON pending_actions(owner_identity);
        CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status);

        -- Research Evidence Ledger per Run
        CREATE TABLE IF NOT EXISTS evidence_ledger (
            id             SERIAL PRIMARY KEY,
            run_id         TEXT NOT NULL,
            claim          TEXT NOT NULL,
            source_url     TEXT NOT NULL,
            verbatim_quote TEXT NOT NULL,
            retrieved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_date TEXT,
            authority_tier TEXT NOT NULL,
            verdict        TEXT NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_ledger_run ON evidence_ledger(run_id);

        -- Unguessable Revocable Share Tokens
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS share_token UUID UNIQUE;
        CREATE INDEX IF NOT EXISTS idx_conversations_share_token ON conversations(share_token);

        -- Memory Unique Content Hash per User
        ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS content_hash TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_chunks_user_hash ON memory_chunks(user_id, content_hash);

        -- Guest Mint Log for Abuse & Global Cap Enforcement
        CREATE TABLE IF NOT EXISTS guest_mint_log (
            id SERIAL PRIMARY KEY,
            guest_id TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_guest_mint_created ON guest_mint_log(created_at);

        -- Persistent Profile Facts Memory
        CREATE TABLE IF NOT EXISTS user_profile_facts (
            id                 SERIAL        PRIMARY KEY,
            user_id            TEXT          NOT NULL DEFAULT 'default_user',
            key                TEXT          NOT NULL,
            value              TEXT          NOT NULL,
            source_message_id  INTEGER       REFERENCES messages(id) ON DELETE SET NULL,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(user_id, key)
        );
        CREATE INDEX IF NOT EXISTS idx_user_profile_facts_user ON user_profile_facts(user_id);

        -- Parked Thoughts — "Park it" shelf for deferred ideas & tangents
        CREATE TABLE IF NOT EXISTS parked_thoughts (
            id                 SERIAL        PRIMARY KEY,
            user_id            TEXT          NOT NULL DEFAULT 'default_user',
            conversation_id    TEXT,
            text               TEXT          NOT NULL,
            status             TEXT          NOT NULL DEFAULT 'parked',
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_parked_thoughts_user_status ON parked_thoughts(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_parked_thoughts_conversation ON parked_thoughts(conversation_id);
        """)


async def init_pool(dsn: str | None = None) -> asyncpg.Pool:
    """Create the connection pool. Safe to call multiple times (idempotent).

    Args:
        dsn: PostgreSQL connection string. If None, reads from settings.
    """
    global _pool, _tables_ensured
    import asyncio

    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    if _pool is not None:
        pool_loop = getattr(_pool, "_loop", None)
        if pool_loop is not None and not pool_loop.is_closed() and (cur_loop is None or pool_loop is cur_loop):
            return _pool
        try:
            _pool.terminate()
        except Exception:
            pass
        _pool = None

    if dsn is None:
        from backend.config import get_settings
        dsn = get_settings().DATABASE_URL

    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        timeout=15.0,
        command_timeout=15.0,
        init=_init_connection,  # register pgvector on every connection
    )
    if not _tables_ensured:
        try:
            await asyncio.wait_for(_ensure_tables(_pool), timeout=15.0)
        except Exception as e:
            import logging
            logging.getLogger("compass.db").warning(f"Could not auto-create tables: {e}")

        # Verify critical tables exist; never silently degrade
        try:
            async with _pool.acquire(timeout=10.0) as check_conn:
                existing_tables = await check_conn.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('user_profile_facts', 'parked_thoughts')"
                )
                found = {r["table_name"] for r in existing_tables}
                import logging
                db_logger = logging.getLogger("compass.db")
                for req_table in ("user_profile_facts", "parked_thoughts"):
                    if req_table not in found:
                        db_logger.error(f"ERROR: Required database table '{req_table}' is missing! Feature will degrade.")
        except Exception as e:
            import logging
            logging.getLogger("compass.db").warning(f"Could not verify table existence at startup: {e}")
        _tables_ensured = True

    return _pool  # type: ignore[return-value]


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool or initialize if not yet created or loop is closed."""
    global _pool
    import asyncio

    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    if _pool is not None:
        pool_loop = getattr(_pool, "_loop", None)
        if pool_loop is None or pool_loop.is_closed() or (cur_loop and pool_loop is not cur_loop):
            try:
                _pool.terminate()
            except Exception:
                pass
            _pool = None

    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        p = _pool
        _pool = None
        pool_loop = getattr(p, "_loop", None)
        if pool_loop is not None and pool_loop.is_closed():
            try:
                p.terminate()
            except Exception:
                pass
            return
        try:
            import asyncio
            await asyncio.wait_for(p.close(), timeout=2.0)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

