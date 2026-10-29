"""
Tests for embedding failure handling and synthetic vector elimination (Step 4).
"""

import pytest
from unittest.mock import AsyncMock, patch
from backend.memory.db import get_pool
from backend.services.embeddings import (
    get_embedding,
    get_embedding_sync,
    get_embedding_failure_count,
    reset_embedding_failure_count,
    compute_historical_fallback_embedding,
    is_historical_fallback_embedding,
)
from backend.memory.vector import store_chunk, search_chunks
from backend.skills.handlers.context import handle_query_code_context


@pytest.fixture(autouse=True)
def reset_counts():
    reset_embedding_failure_count()
    yield
    reset_embedding_failure_count()


@pytest.mark.asyncio
async def test_get_embedding_returns_none_when_unconfigured():
    """get_embedding returns None and increments failure count when key is unconfigured."""
    with patch("backend.services.embeddings._get_api_key", return_value=""):
        result = await get_embedding("test semantic query")
        assert result is None
        assert get_embedding_failure_count() >= 1


def test_get_embedding_sync_returns_none_when_unconfigured():
    """get_embedding_sync returns None and increments failure count when key is unconfigured."""
    with patch("backend.services.embeddings._get_api_key", return_value=""):
        result = get_embedding_sync("test sync query")
        assert result is None
        assert get_embedding_failure_count() >= 1


@pytest.mark.asyncio
async def test_store_chunk_skips_write_on_embedding_failure():
    """store_chunk does not write to database when embedding is unavailable."""
    pool = await get_pool()
    if not pool:
        pytest.skip("Database not available")
    async with pool.acquire() as conn:
        with patch("backend.memory.vector.get_embedding", AsyncMock(return_value=None)):
            res = await store_chunk(
                conn,
                content="Important architecture decision unique 999",
                domain="code",
                user_id="test-user-step4",
            )
            assert res.get("status") == "pending_retry"
            assert res.get("reason") == "embedding_unavailable"

            # Verify nothing was written to memory_chunks
            row = await conn.fetchrow(
                "SELECT id FROM memory_chunks WHERE user_id = $1 AND content = $2",
                "test-user-step4",
                "Important architecture decision unique 999",
            )
            assert row is None


@pytest.mark.asyncio
async def test_search_chunks_skips_retrieval_on_embedding_failure():
    """search_chunks skips vector retrieval and returns empty list when embedding fails."""
    pool = await get_pool()
    if not pool:
        pytest.skip("Database not available")
    async with pool.acquire() as conn:
        with patch("backend.memory.vector.get_embedding", AsyncMock(return_value=None)):
            results = await search_chunks(
                conn,
                query="machine learning architecture",
                domain="code",
                user_id="test-user-step4",
            )
            assert results == []


@pytest.mark.asyncio
async def test_query_code_context_returns_clear_unavailable_status():
    """handle_query_code_context returns 'Semantic search is unavailable right now'."""
    pool = await get_pool()
    if not pool:
        pytest.skip("Database not available")
    with patch("backend.services.embeddings.get_embedding", AsyncMock(return_value=None)):
        res = await handle_query_code_context(
            {"query": "Explain the pipeline forwarding", "domain": "code", "user_id": "test-user-step4"},
            pool,
        )
        assert "Semantic search is unavailable right now." in res["response"]
        assert res["data"]["status"] == "unavailable"
        assert res["data"]["count"] == 0


def test_is_historical_fallback_embedding_detection():
    """Correctly detects historical fallback vectors and rejects real vectors."""
    text = "CS 61C Coursework Lab 4 Architecture"
    fallback_vec = compute_historical_fallback_embedding(text, 768)
    assert is_historical_fallback_embedding(fallback_vec, text, 768) is True

    # Real vector or modified vector should not match
    real_vec = [0.05] * 768
    assert is_historical_fallback_embedding(real_vec, text, 768) is False

    # Different text should not match
    assert is_historical_fallback_embedding(fallback_vec, "Different text", 768) is False
