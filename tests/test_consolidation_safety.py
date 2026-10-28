"""
Regression tests for the nightly consolidation job.

Covers: per-tenant vector dedup, archival that keeps advancing past already-archived
conversations and keeps the owner, dry-run leaving data untouched, and single-flight locking.
"""

import uuid

import asyncpg
import pytest
import pytest_asyncio
from pgvector.asyncpg import register_vector

from backend.config import get_settings
from backend.jobs import consolidate
from backend.jobs.consolidate import (
    CONSOLIDATION_LOCK_KEY,
    archive_stale_threads,
    deduplicate_vectors,
    run_consolidation,
)

settings = get_settings()
VECTOR = [0.1] * 768


@pytest_asyncio.fixture
async def conn():
    connection = await asyncpg.connect(settings.DATABASE_URL)
    await register_vector(connection)
    await connection.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id TEXT, ADD COLUMN IF NOT EXISTS guest_id TEXT"
    )
    try:
        yield connection
    finally:
        await connection.close()


async def _insert_chunk(conn, user_id, source="note/test"):
    return await conn.fetchval(
        "INSERT INTO memory_chunks (domain, content, embedding, source, user_id) "
        "VALUES ('general', $1, $2, $3, $4) RETURNING id",
        f"duplicate content {uuid.uuid4().hex}",
        VECTOR,
        source,
        user_id,
    )


async def _chunk_exists(conn, chunk_id) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM memory_chunks WHERE id = $1", chunk_id))


async def _make_conversation(conn, owner, age_days=10, messages=2) -> uuid.UUID:
    cid = await conn.fetchval(
        "INSERT INTO conversations (last_active_at, user_id) VALUES (now() - ($1 || ' days')::interval, $2) RETURNING id",
        str(age_days),
        owner,
    )
    for i in range(messages):
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            cid,
            "user" if i % 2 == 0 else "assistant",
            f"message {i}",
        )
    return cid


@pytest.fixture(autouse=True)
def _stub_summarizer(monkeypatch):
    async def fake_summary(client, messages):
        return f"summary of {len(messages)} messages"

    async def fake_embedding(text):
        return VECTOR

    async def fake_radar_sync(*args, **kwargs):
        return {"status": "completed", "records_updated": 0}

    async def fake_proactive_run(*args, **kwargs):
        return {"status": "skipped", "run_id": None}

    monkeypatch.setattr(consolidate, "summarize_messages", fake_summary)
    monkeypatch.setattr(consolidate, "get_embedding", fake_embedding)
    monkeypatch.setattr("backend.services.radar_sync.run_radar_sync", fake_radar_sync)
    monkeypatch.setattr(consolidate, "trigger_proactive_nightly_run", fake_proactive_run)


@pytest.mark.asyncio
async def test_dedup_never_deletes_another_tenants_chunk(conn):
    tenant_a, tenant_b = f"a_{uuid.uuid4().hex[:8]}", f"b_{uuid.uuid4().hex[:8]}"
    chunk_a = await _insert_chunk(conn, tenant_a)
    chunk_b = await _insert_chunk(conn, tenant_b)

    await deduplicate_vectors(conn, threshold=0.95, dry_run=False)

    assert await _chunk_exists(conn, chunk_a)
    assert await _chunk_exists(conn, chunk_b)


@pytest.mark.asyncio
async def test_dedup_still_prunes_duplicates_within_one_tenant(conn):
    tenant = f"a_{uuid.uuid4().hex[:8]}"
    older = await _insert_chunk(conn, tenant)
    newer = await _insert_chunk(conn, tenant)

    await deduplicate_vectors(conn, threshold=0.95, dry_run=False)

    assert await _chunk_exists(conn, older)
    assert not await _chunk_exists(conn, newer)


@pytest.mark.asyncio
async def test_dedup_never_prunes_archive_summaries(conn):
    tenant = f"a_{uuid.uuid4().hex[:8]}"
    note = await _insert_chunk(conn, tenant)
    archive = await _insert_chunk(conn, tenant, source=f"archive/conversation/{uuid.uuid4()}")

    await deduplicate_vectors(conn, threshold=0.95, dry_run=False)

    assert await _chunk_exists(conn, note)
    assert await _chunk_exists(conn, archive)


@pytest.mark.asyncio
async def test_archival_advances_past_already_archived_conversations(conn):
    owner = f"user_{uuid.uuid4().hex[:8]}"
    conv_ids = [await _make_conversation(conn, owner, age_days=400 + i) for i in range(7)]

    # Each run handles at most 5 conversations; it must keep advancing until none are left.
    for _ in range(20):
        if await archive_stale_threads(conn, None, stale_days=7) == 0:
            break

    archived = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_chunks WHERE source = ANY($1::text[])",
        [f"archive/conversation/{cid}" for cid in conv_ids],
    )
    assert archived == 7


@pytest.mark.asyncio
async def test_archived_summary_belongs_to_the_conversation_owner(conn):
    owner = f"user_{uuid.uuid4().hex[:8]}"
    cid = await _make_conversation(conn, owner, age_days=500)

    await archive_stale_threads(conn, None, stale_days=7)

    chunk_owner = await conn.fetchval(
        "SELECT user_id FROM memory_chunks WHERE source = $1", f"archive/conversation/{cid}"
    )
    assert chunk_owner == owner


@pytest.mark.asyncio
async def test_dry_run_leaves_stale_guest_conversations_and_buckets(conn):
    guest_conv = await conn.fetchval(
        "INSERT INTO conversations (last_active_at, user_id) VALUES (now() - interval '400 days', $1) RETURNING id",
        f"guest_{uuid.uuid4().hex[:8]}",
    )
    bucket_key = f"test:bucket:{uuid.uuid4().hex}"
    await conn.execute(
        "INSERT INTO rate_limit_buckets (key, tokens, last_updated) VALUES ($1, 1, now() - interval '3 days')",
        bucket_key,
    )

    report = await run_consolidation(dry_run=True)

    assert report["status"] == "completed"
    assert await conn.fetchval("SELECT 1 FROM conversations WHERE id = $1", guest_conv)
    assert await conn.fetchval("SELECT 1 FROM rate_limit_buckets WHERE key = $1", bucket_key)


@pytest.mark.asyncio
async def test_overlapping_consolidation_runs_are_skipped(conn):
    holder = await asyncpg.connect(settings.DATABASE_URL)
    try:
        assert await holder.fetchval("SELECT pg_try_advisory_lock($1)", CONSOLIDATION_LOCK_KEY)
        report = await run_consolidation(dry_run=True)
        assert report == {"status": "skipped", "reason": "already_running"}
    finally:
        await holder.close()


@pytest.mark.asyncio
async def test_admin_endpoint_surfaces_a_skipped_run(client, auth_headers, monkeypatch):
    async def fake_run(**kwargs):
        return {"status": "skipped", "reason": "already_running"}

    monkeypatch.setattr("backend.jobs.consolidate.run_consolidation", fake_run)
    res = await client.post("/admin/consolidate", json={"dry_run": True}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_a_normal_user_session(client):
    from backend.routers.auth import create_session

    res = await client.post(
        "/admin/consolidate",
        json={"dry_run": True},
        headers={"Authorization": f"Bearer {create_session('someone@example.com')}"},
    )
    assert res.status_code == 401
