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

# Match prod by endpoint id from env PROD_DB_ENDPOINT
prod_endpoint_id = os.environ.get("PROD_DB_ENDPOINT", "ep-sweet-fire-b2y9w95z").strip()

if not (os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")):
    env_file = _project_root / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass

test_db_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

# Set DATABASE_URL from test_db_url before importing backend
if test_db_url:
    os.environ["DATABASE_URL"] = test_db_url

from backend.main import app
from backend.config import get_settings

settings = get_settings()


def pytest_configure(config):
    """Guard against executing test runs against production database."""
    if not test_db_url:
        pytest.exit(
            "ABORTED: Neither TEST_DATABASE_URL nor DATABASE_URL environment variable is set. Refusing to run tests.",
            returncode=1,
        )

    parsed_test = urlparse(test_db_url)
    if prod_endpoint_id and prod_endpoint_id in (parsed_test.hostname or ""):
        pytest.exit(
            f"ABORTED: Database matches production endpoint '{prod_endpoint_id}': {parsed_test.hostname}",
            returncode=1,
        )

    parsed_settings = urlparse(settings.DATABASE_URL)
    if prod_endpoint_id and prod_endpoint_id in (parsed_settings.hostname or ""):
        pytest.exit(
            f"ABORTED: settings.DATABASE_URL matches production endpoint '{prod_endpoint_id}': {parsed_settings.hostname}",
            returncode=1,
        )


@pytest_asyncio.fixture
async def client():
    """Async HTTP client fixture configured against the FastAPI app instance."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    import asyncio
    await asyncio.sleep(0.05)


@pytest.fixture
def auth_headers():
    """Valid authorization bearer header fixture."""
    return {"Authorization": f"Bearer {settings.AUTH_TOKEN}"}


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db_pool():
    """Ensure database connection pool is closed within the test's event loop."""
    yield
    try:
        from backend.memory.db import close_pool
        await close_pool()
        import asyncio
        await asyncio.sleep(0.05)
    except Exception:
        pass



