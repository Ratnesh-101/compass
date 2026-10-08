import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import backend.memory.db as db_mod

@pytest.mark.asyncio
async def test_pool_init_retry_with_backoff_success():
    """Verify pool initialization retries with backoff on transient failure and succeeds."""
    db_mod._pool = None
    mock_pool = MagicMock()
    mock_pool._loop = asyncio.get_running_loop()
    mock_pool.is_closed = MagicMock(return_value=False)
    
    attempts = 0
    async def mock_create_pool(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError(f"Transient Neon wakeup delay (attempt {attempts})")
        return mock_pool

    with patch("asyncpg.create_pool", side_effect=mock_create_pool):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch.object(db_mod, "_ensure_tables", new_callable=AsyncMock):
                with patch.object(db_mod, "_tables_ensured", True):
                    pool = await db_mod.init_pool(dsn="postgresql://localhost/fake")
                    assert pool == mock_pool
                    assert attempts == 3
                    # Verify backoff sleeps were called: attempt 1 -> 1.5s, attempt 2 -> 3.0s
                    assert mock_sleep.call_count == 2
                    mock_sleep.assert_any_call(1.5)
                    mock_sleep.assert_any_call(3.0)

    db_mod._pool = None

@pytest.mark.asyncio
async def test_pool_init_retry_exhausted_raises():
    """Verify that if all 3 retry attempts fail, the final exception is raised."""
    db_mod._pool = None
    
    async def mock_create_pool_fail(*args, **kwargs):
        raise ConnectionRefusedError("Database unreachable")

    with patch("asyncpg.create_pool", side_effect=mock_create_pool_fail):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ConnectionRefusedError, match="Database unreachable"):
                await db_mod.init_pool(dsn="postgresql://localhost/fake")
            assert mock_sleep.call_count == 2

    db_mod._pool = None
