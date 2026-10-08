"""
Round 13 Audit & Regression Verification Tests.

Validates:
1. User-trusted URL labeling ("User-trusted source") and strict per-user isolation.
2. Past-date handling with a frozen clock (asks user for clarification if year omitted).
3. Cross-user undo negative test (User B cannot revert or delete User A's created tasks).
"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from backend.services.tavily_authority import classify_domain_authority, AuthorityTier
from backend.router import _fallback_route, _extract_task_creation_args


def test_user_trusted_source_label_and_isolation():
    """Verify that user-pinned URLs get the 'User-trusted source' badge strictly for the pinning user."""
    pinned_url = "https://myhackathon.devpost.com"
    target_page = "https://myhackathon.devpost.com/rules"

    # User A has pinned the URL
    auth_user_a = classify_domain_authority(target_page, trusted_event_url=pinned_url)
    assert auth_user_a["tier"] == AuthorityTier.TIER_1_OFFICIAL.value
    assert auth_user_a["badge"] == "User-trusted source"
    assert "Matched per-user trusted event URL" in auth_user_a["reason"]

    # User B has NOT pinned this URL (trusted_event_url is None or different)
    auth_user_b = classify_domain_authority(target_page, trusted_event_url=None)
    # Devpost without pinning is classified as standard platform host
    assert auth_user_b["badge"] != "User-trusted source"
    assert auth_user_b["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    # Different URL for User A does not get the badge
    other_page = "https://someotherproject.devpost.com"
    auth_other = classify_domain_authority(other_page, trusted_event_url=pinned_url)
    assert auth_other["badge"] != "User-trusted source"


def test_past_date_asks_user_for_clarification():
    """Verify that a task request with a past date and no year prompts the user instead of creating a task."""
    with patch("backend.router.date") as mock_date:
        # Freeze today to Oct 8, 2026
        mock_date.today.return_value = date(2026, 10, 8)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        # 1. Past date (Oct 5) without explicit year
        msg_past = "add a deadline on 5th of October 23:59 with the name finish report"
        skill, args, resp = _fallback_route(msg_past)
        assert skill is None
        assert args is None
        assert "Oct 5 has passed; did you mean 2027?" in resp

        # 2. Future date (Oct 10) creates task normally
        msg_future = "add a deadline on 10th of October 23:59 with the name finish report"
        skill_fut, args_fut, resp_fut = _fallback_route(msg_future)
        assert skill_fut == "add_task"
        assert args_fut["title"] == "Finish report"
        assert "2026-10-10" in args_fut["due_date"]

        # 3. Explicit past year (Oct 5 2025) allows explicit year intent
        msg_explicit = "add a deadline on 5th of October 2025 with the name historic task"
        skill_exp, args_exp, resp_exp = _fallback_route(msg_explicit)
        assert skill_exp == "add_task"
        assert args_exp["title"] == "Historic task"


@pytest.mark.asyncio
async def test_undo_cross_user_isolation():
    """Verify that User B cannot undo or delete a task created by User A."""
    from backend.orchestrator import handle_message
    from backend.memory.db import get_pool
    from backend.memory import structured

    pool = await get_pool()
    if not pool:
        pytest.skip("Database pool not available for live DB test")

    user_a = "test_user_round13_a"
    user_b = "test_user_round13_b"

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id IN ($1, $2)", user_a, user_b)
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by IN ($1, $2)", user_a, user_b)

    try:
        # User A creates a task
        res_a = await handle_message(
            message="add a deadline on 10th of October 23:59 with the name task for user a",
            user_id=user_a,
            persist=False,
        )
        assert res_a["skill_used"] == "add_task"
        task_a_id = res_a["data"]["id"]

        # User B attempts to call 'undo'
        res_b = await handle_message(
            message="undo",
            user_id=user_b,
            persist=False,
        )
        # User B's undo should NOT find any task to revert
        assert "nothing to undo" in res_b["response"].lower() or res_b["skill_used"] != "undo" or not res_b.get("success")

        # Verify User A's task still exists untouched in the database
        async with pool.acquire() as conn:
            task_a = await structured.get_task(conn, task_a_id)
            assert task_a is not None
            assert task_a["user_id"] == user_a
            assert "task for user a" in task_a["title"].lower()

    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE user_id IN ($1, $2)", user_a, user_b)
            await conn.execute("DELETE FROM agent_audit_log WHERE approved_by IN ($1, $2)", user_a, user_b)
