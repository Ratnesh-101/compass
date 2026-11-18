import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.memory.db import get_pool


@pytest.mark.asyncio
async def test_projects_multitenant_leakage_verified():
    """SEC-06 regression: GET /projects only lists projects holding the caller's own tasks.

    (Originally demonstrated the leak; the projects table still has no user_id column.)
    """
    pool = await get_pool()
    if not pool:
        pytest.skip("Database pool unavailable")

    project_name = "Tenant-A-Secret-Project-Audit219"
    async with pool.acquire() as conn:
        # Clean up any leftover row
        await conn.execute("DELETE FROM projects WHERE name = $1", project_name)
        # User A inserts a project
        await conn.execute(
            "INSERT INTO projects (name, domain, description) VALUES ($1, $2, $3)",
            project_name,
            "hackathon",
            "Confidential Project Data for Tenant A",
        )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # User B requests /projects
            resp = await client.get(
                "/projects",
                headers={"x-user-id": "user_tenant_b"},
            )
            assert resp.status_code == 200
            data = resp.json()
            project_names = [p["name"] for p in data.get("projects", [])]
            # Fixed: a project with none of tenant B's tasks is not listed for B.
            assert project_name not in project_names, "Tenant B must not see Tenant A's project"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM projects WHERE name = $1", project_name)
