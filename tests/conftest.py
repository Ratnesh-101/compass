"""
Compass — Pytest Configuration & Test Fixtures.
"""

import sys
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from backend.main import app
from backend.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client fixture configured against the FastAPI app instance."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    """Valid authorization bearer header fixture."""
    return {"Authorization": f"Bearer {settings.AUTH_TOKEN}"}
