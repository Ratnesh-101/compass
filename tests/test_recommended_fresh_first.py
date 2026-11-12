import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.memory.radar import upsert_opportunity, upsert_opportunity_requirements
from backend.models_radar import OpportunityStatus


async def _seed_open(tag: str, verified_days_ago: int, skills=None) -> int:
    oid = await upsert_opportunity(
        company_name=f"FreshCo{tag}",
        role_title=f"Intern {tag}",
        canonical_url=f"https://fresh.example/{tag}",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="India",
        is_india_eligible=True,
        last_verified_at=datetime.now(timezone.utc) - timedelta(days=verified_days_ago),
    )
    reqs = dict(eligible_graduation_years=[2027], eligible_degree_types=["B.Tech"])
    if skills:
        reqs["required_skills"] = skills
    await upsert_opportunity_requirements(oid, reqs)
    return oid


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_recently_verified_open_listings_rank_above_ones_needing_recheck():
    tag = uuid.uuid4().hex[:6]
    # The stale listing matches the candidate's skills better, so the OLD ranking put it first.
    stale_id = await _seed_open(f"stale{tag}", verified_days_ago=25, skills=["python"])
    fresh_id = await _seed_open(f"fresh{tag}", verified_days_ago=2)
    user = f"fresh_user_{tag}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"x-user-id": user}) as c:
        r = await c.put("/api/opportunities/profile", json={"degree": "B.Tech", "academic_year": 3, "grad_year": 2027, "cgpa": 8.0, "skills": ["python"]})
        assert r.status_code == 200
        rec = await c.get("/api/opportunities/recommended?limit=50")
        assert rec.status_code == 200
        ordered = [o["id"] for o in rec.json()]
        assert fresh_id in ordered and stale_id in ordered
        assert ordered.index(fresh_id) < ordered.index(stale_id)
        by_id = {o["id"]: o for o in rec.json()}
        assert by_id[fresh_id]["needs_recheck"] is False
        assert by_id[stale_id]["needs_recheck"] is True
