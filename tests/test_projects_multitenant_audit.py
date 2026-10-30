import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.memory.db import get_pool


@pytest.mark.asyncio
async def test_projects_multitenant_leakage_verified():
    """SEC-06 Verification: Demonstrates that GET /projects returns projects globally

    across all users because the 'projects' schema lacks a user_id column.
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
            # VERIFIED-REAL: Tenant B can see Tenant A's project!
            assert project_name in project_names, "Tenant B should see Tenant A's project (demonstrating multi-tenant leakage)"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM projects WHERE name = $1", project_name)
