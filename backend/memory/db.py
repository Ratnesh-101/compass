"""
Compass — Async database connection pool.

Uses asyncpg with pgvector codec registration.
The pool registers the vector type on every new connection via the `init` callback,
so all connections in the pool can read/write VECTOR columns.
"""
from __future__ import annotations

import time
import logging
import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger("compass.db")


_pool: asyncpg.Pool | None = None
_tables_ensured: bool = False


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Called for every new connection in the pool.
    Registers the pgvector type codec so asyncpg can handle VECTOR columns."""
    await register_vector(conn)


async def _ensure_tables(pool: asyncpg.Pool) -> None:
    """Create agent_runs and agent_audit_log tables if they don't already exist."""
    global _tables_ensured
    if _tables_ensured:
        return
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
        ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id         ON agent_runs(user_id);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status          ON agent_runs(status);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at      ON agent_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id ON agent_runs(conversation_id);

        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT,
            ADD COLUMN IF NOT EXISTS user_id TEXT,
            ADD COLUMN IF NOT EXISTS guest_id TEXT,
            ADD COLUMN IF NOT EXISTS imported_from_id UUID,
            ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_conversations_last_active ON conversations(last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conversations_guest_id ON conversations(guest_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_imported_from ON conversations(imported_from_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_is_shared ON conversations(is_shared);

        CREATE TABLE IF NOT EXISTS guest_migration_log (
            id                      SERIAL        PRIMARY KEY,
            guest_id                TEXT          NOT NULL,
            user_id                 TEXT          NOT NULL,
            guest_conversation_id   UUID,
            user_conversation_id    UUID,
            entity_type             TEXT          NOT NULL DEFAULT 'conversation',
            entity_key              TEXT,
            detail                  JSONB         DEFAULT '{}'::jsonb,
            imported_at             TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE guest_migration_log ALTER COLUMN guest_conversation_id DROP NOT NULL;
        ALTER TABLE guest_migration_log ALTER COLUMN user_conversation_id DROP NOT NULL;
        ALTER TABLE guest_migration_log ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'conversation',
            ADD COLUMN IF NOT EXISTS entity_key TEXT,
            ADD COLUMN IF NOT EXISTS detail JSONB DEFAULT '{}'::jsonb;
        CREATE INDEX IF NOT EXISTS idx_guest_mig_guest ON guest_migration_log(guest_id);
        CREATE INDEX IF NOT EXISTS idx_guest_mig_user ON guest_migration_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_guest_mig_entity ON guest_migration_log(guest_id, user_id, entity_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_guest_mig_conv_uniq ON guest_migration_log(guest_conversation_id, user_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_guest_mig_entity_uniq ON guest_migration_log(guest_id, user_id, entity_type, entity_key) WHERE entity_key IS NOT NULL;
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE indexname = 'idx_guest_mig_conv_uniq' 
                AND indexdef LIKE '%WHERE%'
            ) THEN
                DROP INDEX idx_guest_mig_conv_uniq;
                CREATE UNIQUE INDEX idx_guest_mig_conv_uniq ON guest_migration_log(guest_conversation_id, user_id);
            END IF;
        END $$;

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
        ALTER TABLE tavily_usage_log ADD COLUMN IF NOT EXISTS identity TEXT;
        CREATE INDEX IF NOT EXISTS idx_tavily_usage_identity_created ON tavily_usage_log(identity, created_at);
        ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
        -- Dynamic Scheduling & Calendar Extensions
        ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_domain_check;
        ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_domain_check;
        ALTER TABLE memory_chunks DROP CONSTRAINT IF EXISTS memory_chunks_domain_check;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id VARCHAR(255) DEFAULT 'default_user',
            ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 60,
            ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS scheduled_end TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS is_fixed BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS recurrence_rule TEXT,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;
        CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id); CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_start ON tasks(scheduled_start);
        CREATE INDEX IF NOT EXISTS idx_tasks_deleted_at ON tasks(deleted_at);
        ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS user_id VARCHAR(255) DEFAULT 'default_user', ADD COLUMN IF NOT EXISTS needs_reindex BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_user_id ON memory_chunks(user_id);
        CREATE TABLE IF NOT EXISTS chat_pending_actions (
            id SERIAL PRIMARY KEY, action TEXT NOT NULL, task_ids INTEGER[] NOT NULL DEFAULT '{}'::integer[],
            task_titles JSONB NOT NULL DEFAULT '[]'::jsonb, count INTEGER NOT NULL DEFAULT 1,
            owner_identity TEXT NOT NULL, conversation_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL, executed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_chat_pending_owner_conv ON chat_pending_actions(owner_identity, conversation_id, status);
        CREATE INDEX IF NOT EXISTS idx_chat_pending_expires ON chat_pending_actions(expires_at);
        ALTER TABLE messages ADD COLUMN IF NOT EXISTS verifiable BOOLEAN DEFAULT FALSE;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
        CREATE TABLE IF NOT EXISTS chat_request_log (owner_identity TEXT NOT NULL, request_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', response JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (owner_identity, request_id));
        CREATE INDEX IF NOT EXISTS idx_chat_request_log_created ON chat_request_log(created_at);

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

            CREATE TABLE IF NOT EXISTS oauth_consumed_states (
                state_sig          TEXT          PRIMARY KEY,
                user_id            TEXT          NOT NULL,
                action             TEXT          NOT NULL,
                consumed_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
                expires_at         TIMESTAMPTZ   NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_oauth_consumed_expires ON oauth_consumed_states(expires_at);

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

        -- Persisted Verification Evidence on Messages
        ALTER TABLE messages ADD COLUMN IF NOT EXISTS evidence JSONB;

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

        -- Per-task and per-user trusted event URLs
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS trusted_event_url TEXT;

        CREATE TABLE IF NOT EXISTS user_trusted_urls (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, url)
        );
        CREATE INDEX IF NOT EXISTS idx_user_trusted_urls_user ON user_trusted_urls(user_id);

        -- ============================================================
        -- Internship Radar Tables
        -- ============================================================
        CREATE TABLE IF NOT EXISTS opportunities (
            id                          SERIAL        PRIMARY KEY,
            company_name                TEXT          NOT NULL,
            normalized_company          TEXT          NOT NULL,
            role_title                  TEXT          NOT NULL,
            opportunity_type            TEXT          NOT NULL DEFAULT 'internship',
            category                    TEXT          NOT NULL DEFAULT 'general',
            location                    TEXT,
            work_arrangement            TEXT          NOT NULL DEFAULT 'unknown',
            country                     TEXT          NOT NULL DEFAULT 'India',
            is_india_eligible           BOOLEAN       NOT NULL DEFAULT TRUE,
            compensation                TEXT,
            duration                    TEXT,
            official_application_url    TEXT,
            canonical_url               TEXT          UNIQUE NOT NULL,
            current_status              TEXT          NOT NULL DEFAULT 'DISCOVERED',
            confirmed_open_date         DATE,
            confirmed_close_date        DATE,
            description                 TEXT,
            last_verified_at            TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(current_status);
        CREATE INDEX IF NOT EXISTS idx_opportunities_category ON opportunities(category);
        CREATE INDEX IF NOT EXISTS idx_opportunities_company ON opportunities(normalized_company);
        CREATE INDEX IF NOT EXISTS idx_opportunities_india ON opportunities(is_india_eligible);
        CREATE INDEX IF NOT EXISTS idx_opportunities_dates ON opportunities(confirmed_close_date, confirmed_open_date);

        ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS employer_type TEXT NOT NULL DEFAULT 'enterprise',
            ADD COLUMN IF NOT EXISTS verification_evidence TEXT,
            ADD COLUMN IF NOT EXISTS employer_identity_verified BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS official_source_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS application_url_checked BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS posted_at_precision TEXT NOT NULL DEFAULT 'unknown';
        CREATE INDEX IF NOT EXISTS idx_opportunities_employer_type ON opportunities(employer_type);

        CREATE TABLE IF NOT EXISTS opportunity_sources (
            id                  SERIAL        PRIMARY KEY,
            opportunity_id      INTEGER       NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            source_name         TEXT          NOT NULL,
            source_type         TEXT          NOT NULL,
            source_url          TEXT          NOT NULL,
            source_authority    TEXT          NOT NULL DEFAULT 'tier_2',
            content_hash        TEXT,
            raw_data            JSONB         DEFAULT '{}'::jsonb,
            discovered_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
            last_checked_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            verification_result TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_opp_sources_opp_id ON opportunity_sources(opportunity_id);
        CREATE INDEX IF NOT EXISTS idx_opp_sources_type ON opportunity_sources(source_type);

        CREATE TABLE IF NOT EXISTS opportunity_requirements (
            id                           SERIAL        PRIMARY KEY,
            opportunity_id               INTEGER       NOT NULL UNIQUE REFERENCES opportunities(id) ON DELETE CASCADE,
            eligible_degree_types        TEXT[]        DEFAULT ARRAY[]::TEXT[],
            eligible_academic_years      INT[]         DEFAULT ARRAY[]::INT[],
            eligible_graduation_years    INT[]         DEFAULT ARRAY[]::INT[],
            eligible_countries           TEXT[]        DEFAULT ARRAY[]::TEXT[],
            work_auth_required           BOOLEAN,
            sponsorship_available        BOOLEAN,
            required_skills              TEXT[]        DEFAULT ARRAY[]::TEXT[],
            min_gpa                      NUMERIC(3, 2),
            other_mandatory_requirements TEXT,
            unknown_requirements         TEXT[]        DEFAULT ARRAY[]::TEXT[],
            last_updated_at              TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE opportunity_requirements ADD COLUMN IF NOT EXISTS preferred_skills TEXT[] DEFAULT ARRAY[]::TEXT[],
            ADD COLUMN IF NOT EXISTS gpa_scale NUMERIC(4, 2) DEFAULT 10.0,
            ADD COLUMN IF NOT EXISTS no_active_backlogs BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS has_conflicting_requirements BOOLEAN DEFAULT FALSE;

        CREATE TABLE IF NOT EXISTS opportunity_cycles (
            id                  SERIAL        PRIMARY KEY,
            opportunity_id      INTEGER       NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            cycle_year          INTEGER       NOT NULL,
            observed_open_date  DATE,
            observed_close_date DATE,
            date_precision      TEXT          NOT NULL DEFAULT 'day',
            verification_status TEXT          NOT NULL DEFAULT 'verified',
            observation_type    TEXT          NOT NULL DEFAULT 'confirmed',
            notes               TEXT,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(opportunity_id, cycle_year)
        );
        CREATE INDEX IF NOT EXISTS idx_opp_cycles_opp ON opportunity_cycles(opportunity_id);
        CREATE INDEX IF NOT EXISTS idx_opp_cycles_year ON opportunity_cycles(cycle_year);

        CREATE TABLE IF NOT EXISTS user_opportunity_profiles (
            id                          SERIAL        PRIMARY KEY,
            user_id                     TEXT          NOT NULL UNIQUE,
            degree                      TEXT,
            degree_specialization       TEXT,
            university                  TEXT,
            academic_year               INT,
            grad_month                  INT           DEFAULT 6,
            grad_year                   INT,
            country_of_study            TEXT          DEFAULT 'India',
            country_of_residence        TEXT          DEFAULT 'India',
            preferred_locations         TEXT[]        DEFAULT ARRAY['India', 'Remote']::TEXT[],
            preferred_work_arrangements TEXT[]        DEFAULT ARRAY['remote', 'hybrid', 'onsite']::TEXT[],
            preferred_roles             TEXT[]        DEFAULT ARRAY[]::TEXT[],
            skills                      TEXT[]        DEFAULT ARRAY[]::TEXT[],
            min_compensation            TEXT,
            resume_url                  TEXT,
            cgpa                        DOUBLE PRECISION,
            cgpa_scale                  DOUBLE PRECISION DEFAULT 10.0,
            active_backlogs             INT DEFAULT 0,
            work_authorization          TEXT DEFAULT 'India',
            requires_sponsorship        BOOLEAN DEFAULT FALSE,
            created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_user_opp_prof_user ON user_opportunity_profiles(user_id);
        ALTER TABLE user_opportunity_profiles ADD COLUMN IF NOT EXISTS cgpa DOUBLE PRECISION;
        ALTER TABLE user_opportunity_profiles ADD COLUMN IF NOT EXISTS cgpa_scale DOUBLE PRECISION DEFAULT 10.0;
        ALTER TABLE user_opportunity_profiles ADD COLUMN IF NOT EXISTS active_backlogs INT DEFAULT 0;
        ALTER TABLE user_opportunity_profiles ADD COLUMN IF NOT EXISTS work_authorization TEXT DEFAULT 'India';
        ALTER TABLE user_opportunity_profiles ADD COLUMN IF NOT EXISTS requires_sponsorship BOOLEAN DEFAULT FALSE;

        CREATE TABLE IF NOT EXISTS user_opportunities (
            id                          SERIAL        PRIMARY KEY,
            user_id                     TEXT          NOT NULL,
            opportunity_id              INTEGER       NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            is_saved                    BOOLEAN       NOT NULL DEFAULT FALSE,
            is_dismissed                BOOLEAN       NOT NULL DEFAULT FALSE,
            application_status          TEXT          NOT NULL DEFAULT 'interested',
            eligibility_classification  TEXT          NOT NULL DEFAULT 'INSUFFICIENT_INFORMATION',
            eligibility_reasons         JSONB         NOT NULL DEFAULT '[]'::jsonb,
            application_date            DATE,
            personal_deadline           DATE,
            interview_date              DATE,
            follow_up_date              DATE,
            private_notes               TEXT,
            created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(user_id, opportunity_id)
        );
        CREATE INDEX IF NOT EXISTS idx_user_opp_user ON user_opportunities(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_opp_saved ON user_opportunities(user_id, is_saved);
        CREATE INDEX IF NOT EXISTS idx_user_opp_status ON user_opportunities(user_id, application_status);

        CREATE TABLE IF NOT EXISTS opportunity_status_history (
            id                  SERIAL        PRIMARY KEY,
            opportunity_id      INTEGER       NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            previous_status     TEXT,
            new_status          TEXT          NOT NULL,
            evidence_source     TEXT,
            reason_for_change   TEXT,
            observed_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_opp_hist_opp ON opportunity_status_history(opportunity_id);

        CREATE TABLE IF NOT EXISTS opportunity_sync_runs (
            id                    SERIAL        PRIMARY KEY,
            source_id             TEXT          NOT NULL,
            source_type           TEXT          NOT NULL,
            status                TEXT          NOT NULL DEFAULT 'running',
            records_discovered    INT           DEFAULT 0,
            records_updated       INT           DEFAULT 0,
            records_skipped       INT           DEFAULT 0,
            verification_failures INT           DEFAULT 0,
            error_summary         TEXT,
            run_started_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
            run_completed_at      TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_opp_sync_source ON opportunity_sync_runs(source_id, run_started_at DESC);

        CREATE TABLE IF NOT EXISTS resumes (
            id                  SERIAL        PRIMARY KEY,
            user_id             TEXT          NOT NULL,
            opportunity_id      INTEGER       REFERENCES opportunities(id) ON DELETE SET NULL,
            is_master           BOOLEAN       NOT NULL DEFAULT FALSE,
            title               TEXT          NOT NULL,
            version             INT           NOT NULL DEFAULT 1,
            content             JSONB         NOT NULL DEFAULT '{}'::jsonb,
            validation_status   TEXT          NOT NULL DEFAULT 'DRAFT',
            validation_report   JSONB         NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id);
        CREATE INDEX IF NOT EXISTS idx_resumes_opp ON resumes(opportunity_id);
        CREATE INDEX IF NOT EXISTS idx_resumes_master ON resumes(user_id, is_master);
        ALTER TABLE resumes ADD COLUMN IF NOT EXISTS cover_letter TEXT;

        CREATE TABLE IF NOT EXISTS career_applications (
            id                  SERIAL        PRIMARY KEY,
            user_id             TEXT          NOT NULL,
            opportunity_id      INTEGER       NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            resume_id           INTEGER       REFERENCES resumes(id) ON DELETE SET NULL,
            status              TEXT          NOT NULL DEFAULT 'SAVED',
            submission_method   TEXT          NOT NULL DEFAULT 'manual_handoff',
            form_answers        JSONB         NOT NULL DEFAULT '{}'::jsonb,
            submission_payload  JSONB         NOT NULL DEFAULT '{}'::jsonb,
            submission_result   JSONB         NOT NULL DEFAULT '{}'::jsonb,
            batch_id            TEXT,
            approved_at         TIMESTAMPTZ,
            submitted_at        TIMESTAMPTZ,
            target_deadline     DATE,
            private_notes       TEXT,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(user_id, opportunity_id)
        );
        ALTER TABLE career_applications ADD COLUMN IF NOT EXISTS cover_letter TEXT;
        CREATE INDEX IF NOT EXISTS idx_career_app_user ON career_applications(user_id);
        CREATE INDEX IF NOT EXISTS idx_career_app_status ON career_applications(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_career_app_batch ON career_applications(batch_id);

        CREATE TABLE IF NOT EXISTS application_batches (
            id                  TEXT          PRIMARY KEY,
            user_id             TEXT          NOT NULL,
            application_ids     INTEGER[]     NOT NULL DEFAULT ARRAY[]::INTEGER[],
            status              TEXT          NOT NULL DEFAULT 'DRAFT',
            approval_token      TEXT,
            approved_at         TIMESTAMPTZ,
            results             JSONB         NOT NULL DEFAULT '[]'::jsonb,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_app_batches_user ON application_batches(user_id);

        CREATE TABLE IF NOT EXISTS application_events (
            id                  SERIAL        PRIMARY KEY,
            application_id      INTEGER       NOT NULL REFERENCES career_applications(id) ON DELETE CASCADE,
            event_type          TEXT          NOT NULL,
            details             JSONB         NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_app_events_app ON application_events(application_id);

        CREATE TABLE IF NOT EXISTS original_resume_documents (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL,
            file_type TEXT NOT NULL, raw_text TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_orig_resumes_user ON original_resume_documents(user_id);
        """)
    _tables_ensured = True


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

    # Retry with exponential backoff for Neon scale-to-zero wakeups and Render cold starts
    max_retries = 3
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            _pool = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=10,
                timeout=30.0,
                command_timeout=30.0,
                init=_init_connection,  # register pgvector on every connection
            )
            break
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                backoff = attempt * 1.5
                logger.warning(f"⚠️ Neon pool init attempt {attempt}/{max_retries} failed ({e}); retrying in {backoff}s...")
                await asyncio.sleep(backoff)
            else:
                raise last_err
    pool = _pool
    if pool is None:
        raise RuntimeError("Database connection pool failed to initialize.")

    if not _tables_ensured:
        try:
            await asyncio.wait_for(_ensure_tables(pool), timeout=15.0)
        except Exception as e:
            logger.error(f"Could not auto-create database tables: {e}")
            raise

        # Verify critical tables exist; never silently degrade
        try:
            async with pool.acquire(timeout=10.0) as check_conn:
                existing_tables = await check_conn.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('user_profile_facts', 'parked_thoughts', 'oauth_consumed_states', 'original_resume_documents')"
                )
                found = {r["table_name"] for r in existing_tables}
                for req_table in ("user_profile_facts", "parked_thoughts", "oauth_consumed_states", "original_resume_documents"):
                    if req_table not in found:
                        logger.error(f"ERROR: Required database table '{req_table}' is missing! Feature will degrade.")
        except Exception as e:
            logger.warning(f"Could not verify table existence at startup: {e}")
        _tables_ensured = True
    return pool


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
        from backend.config import get_settings
        now = time.monotonic()
        if get_settings().is_test() and (now - globals().get("_last_pool_fail_time", 0.0)) < 10.0:
            return None
        try:
            return await init_pool()
        except Exception:
            globals()["_last_pool_fail_time"] = time.monotonic()
            if get_settings().is_test():
                return None
            raise
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

