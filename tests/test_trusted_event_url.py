"""
Tests for DB-backed per-task and per-user trusted event URLs.

Verifies:
1. Tasks can store and update trusted_event_url in PostgreSQL.
2. User can pin trusted event URLs via user_trusted_urls table.
3. Domain authority elevates platform URLs to Tier 1 Official when matching trusted_event_url.
4. Pipeline produces VERIFIED verdict for user-pinned event URLs.
"""

import pytest
from backend.memory.db import get_pool
from backend.memory import structured
from backend.services.tavily_authority import classify_domain_authority, AuthorityTier
from backend.services.tavily_pipeline import evaluate_deterministic_verdict


@pytest.mark.asyncio
async def test_per_task_trusted_event_url_persistence():
    pool = await get_pool()
    test_user = "test_user_trusted_task"
    official_url = "https://nebiusglobalaihackathon.devpost.com/rules"

    async with pool.acquire() as conn:
        # 1. Create task with trusted_event_url
        task = await structured.create_task(
            conn,
            domain="hackathon",
            title="Nebius Hackathon Final Submission",
            due_date=None,
            user_id=test_user,
            trusted_event_url=official_url,
        )
        task_id = task["id"]
        assert task.get("trusted_event_url") == official_url

        # 2. Retrieve task
        retrieved = await structured.get_task(conn, task_id)
        assert retrieved is not None
        assert retrieved["trusted_event_url"] == official_url

        # 3. Update task with modified trusted_event_url
        new_url = "https://nebiusglobalaihackathon.devpost.com/updates"
        updated = await structured.update_task(conn, task_id, trusted_event_url=new_url)
        assert updated is not None
        assert updated["trusted_event_url"] == new_url

        # Clean up
        await structured.delete_task(conn, task_id)


@pytest.mark.asyncio
async def test_per_user_trusted_event_urls_persistence():
    pool = await get_pool()
    test_user = "test_user_pinned_registry"
    pinned_url = "https://nebiusglobalaihackathon.devpost.com"

    async with pool.acquire() as conn:
        # 1. Pin user trusted URL in DB
        res = await structured.set_user_trusted_url(
            conn,
            user_id=test_user,
            url=pinned_url,
            title="Official Nebius x NVIDIA Hackathon Portal",
        )
        assert res["url"] == pinned_url

        # 2. Retrieve user pinned URLs
        urls = await structured.get_user_trusted_urls(conn, test_user)
        assert pinned_url in urls

        # Clean up
        await conn.execute("DELETE FROM user_trusted_urls WHERE user_id = $1", test_user)


def test_trusted_event_url_elevates_to_tier_1_verified():
    devpost_url = "https://nebiusglobalaihackathon.devpost.com/rules"
    quote = "Submissions close: Friday, October 30, 2026 at 10:00am PDT."
    raw_text = f"Nebius x NVIDIA Global AI Hackathon. {quote}"

    # Without trusted_event_url: Tier 2 (Platform host)
    auth_default = classify_domain_authority(devpost_url, pinned_event_prefixes=[])
    assert auth_default["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    # With user-pinned trusted_event_url from DB: elevates to Tier 1 Official
    auth_trusted = classify_domain_authority(devpost_url, trusted_event_url=devpost_url)
    assert auth_trusted["tier"] == AuthorityTier.TIER_1_OFFICIAL.value

    claims = [{
        "claim": "Nebius x NVIDIA Global AI Hackathon submission deadline",
        "source_url": devpost_url,
        "exact_quote": quote,
        "extracted_date": "October 30, 2026",
    }]
    sources = [{"url": devpost_url, "authority_tier": auth_trusted["tier"]}]

    verdict, evidence = evaluate_deterministic_verdict(
        claims, raw_text, sources, target_entity="Nebius x NVIDIA"
    )

    assert verdict == "VERIFIED"
    assert len(evidence) == 1
    assert evidence[0]["verdict"] == "VERIFIED"
    assert evidence[0]["parsed_date"] == "2026-10-30T00:00:00+00:00"
