"""
Compass — Pytest Configuration & Test Fixtures.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Suppress harmless GC teardown warnings when loops close before unexhausted generators
def _quiet_unraisablehook(unraisable):
    if unraisable.exc_value and "Event loop is closed" in str(unraisable.exc_value):
        return
    if hasattr(sys, "__unraisablehook__"):
        sys.__unraisablehook__(unraisable)

sys.unraisablehook = _quiet_unraisablehook

from dotenv import load_dotenv
load_dotenv()

# Capture pre-override production DATABASE_URL and optional configured production marker
_ORIGINAL_PROD_DB_URL = os.environ.get("DATABASE_URL", "").strip()
_CONFIGURED_PROD_MARKER = os.environ.get("PROD_DATABASE_MARKER", "production").strip().lower()

test_db_url = os.environ.get("TEST_DATABASE_URL", "").strip()

# Set DATABASE_URL and ENVIRONMENT before importing backend
if test_db_url:
    os.environ["DATABASE_URL"] = test_db_url
os.environ["ENVIRONMENT"] = "test"

from backend.main import app
from backend.config import get_settings

settings = get_settings()
settings.ENVIRONMENT = "test"
if test_db_url:
    settings.DATABASE_URL = test_db_url


def validate_test_db_guard(
    test_url: str,
    prod_url: str,
    prod_marker: str = "",
) -> None:
    """Validate positive separation between test and production databases.
    Aborts via pytest.exit if test_url is missing, invalid, identical to prod_url,
    or contains prod_marker.
    """
    if not test_url:
        pytest.exit(
            "ABORTED: TEST_DATABASE_URL environment variable is not set. Refusing to run tests against default or production database.",
            returncode=1,
        )

    parsed_test = urlparse(test_url)
    test_hostname = (parsed_test.hostname or "").lower()
    test_db = (parsed_test.path or "").strip("/").lower()

    if not test_hostname:
        pytest.exit(
            "ABORTED: TEST_DATABASE_URL lacks a valid hostname. Refusing to run tests.",
            returncode=1,
        )

    if prod_url:
        parsed_prod = urlparse(prod_url)
        prod_hostname = (parsed_prod.hostname or "").lower()
        prod_db = (parsed_prod.path or "").strip("/").lower()

        # Always verify positive separation: host AND db name must differ
        if prod_hostname and (test_hostname == prod_hostname and test_db == prod_db):
            pytest.exit(
                "ABORTED: TEST_DATABASE_URL targets the identical host and database as DATABASE_URL. Refusing to run tests.",
                returncode=1,
            )

    if prod_marker and prod_marker.lower() in test_hostname:
        pytest.exit(
            f"ABORTED: TEST_DATABASE_URL hostname contains configured production marker '{prod_marker}'.",
            returncode=1,
        )


def pytest_configure(config):
    """Guard against executing test runs against production database."""
    validate_test_db_guard(test_db_url, _ORIGINAL_PROD_DB_URL, _CONFIGURED_PROD_MARKER)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client fixture configured against the FastAPI app instance."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10.0) as ac:
        yield ac
    import asyncio
    await asyncio.sleep(0.05)


@pytest.fixture
def auth_headers():
    """Valid authorization bearer header fixture."""
    return {"Authorization": f"Bearer {settings.AUTH_TOKEN}"}


@pytest_asyncio.fixture(autouse=True)
async def test_db_lifecycle():
    """Clean up test state after each test only if a database pool is already active."""
    yield
    try:
        from backend.dependencies import _rate_store, _agent_rate_store
        _rate_store.clear()
        _agent_rate_store.clear()
    except Exception:
        pass
    try:
        from backend.memory import db
        if db._pool is not None:
            async with db._pool.acquire(timeout=5.0) as conn:
                await conn.execute("""
                    DELETE FROM user_profile_facts WHERE user_id LIKE 'alice_%' OR user_id LIKE 'bob_%' OR user_id LIKE 'carol_%' OR user_id LIKE 'david_%' OR user_id LIKE 'test_%' OR user_id LIKE '%@example.com';
                    DELETE FROM parked_thoughts WHERE user_id LIKE 'alice_%' OR user_id LIKE 'bob_%' OR user_id LIKE 'carol_%' OR user_id LIKE 'david_%' OR user_id LIKE 'test_%' OR user_id LIKE '%@example.com';
                    DELETE FROM rate_limit_buckets;
                    DELETE FROM agent_runs WHERE id LIKE 'test_%' OR id LIKE 'run_%';
                    DELETE FROM pending_actions WHERE run_id LIKE 'test_%' OR run_id LIKE 'run_%';
                """)
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus):
    """Safely terminate asyncpg connection pool once when the entire test session finishes."""
    import asyncio
    try:
        from backend.memory.db import close_pool
        loop = asyncio.new_event_loop()
        loop.run_until_complete(close_pool())
        loop.close()
    except Exception:
        pass





