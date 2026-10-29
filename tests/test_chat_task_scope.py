"""
Compass — chat and dashboard agree on which tasks a user has.

Judge Persona demo rows (trusted_event_url 'compass://demo-persona/%') are hidden from
chat by default exactly like the dashboard, owner scoping is mandatory, and
"delete my overdue deadline" understands the status word instead of searching for it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.memory.chat_pending import (
    get_all_active_tasks_for_user,
    list_nearest_active_titles,
    search_active_tasks_for_delete,
)
from backend.memory.db import get_pool
from backend.orchestrator import handle_message
from backend.services.delete_target import DeleteTarget, normalize_delete_target, parse_delete_target
from backend.services.task_scope import demo_sql_predicate, visible_tasks

DEMO_SLUGS = ["nebius-p1", "cs61c-hw3", "sprint", "ssl-cors"]


def _tenant(label: str = "a") -> str:
    return f"guest_scope_{label}_{uuid.uuid4().hex[:10]}"


async def _insert(conn, owner, title, url=None, due=None, status="open"):
    return await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, trusted_event_url, due_date, status)
        VALUES ($1, 'general', $2, $3, $4, $5) RETURNING id
        """,
        title,
        owner,
        url,
        due,
        status,
    )


async def _seed_mixed(conn, owner):
    real = await _insert(conn, owner, "Real essay draft")
    demo = [
        await _insert(conn, owner, f"Persona item {slug}", url=f"compass://demo-persona/{slug}")
        for slug in DEMO_SLUGS
    ]
    return real, demo


async def _cleanup(pool, *owners):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = ANY($1::text[])", list(owners))
        await conn.execute("DELETE FROM tasks WHERE user_id = ANY($1::text[])", list(owners))


async def _dashboard_ids(owner, include_demo):
    from backend.routers.tasks import get_frontend_tasks

    ident = MagicMock(id=owner, is_guest=True)
    with patch("backend.routers.tasks._get_current_identity", return_value=ident):
        res = await get_frontend_tasks(MagicMock(), domain=None, include_demo=include_demo)
    return [t.id for t in res]


@pytest.mark.asyncio
async def test_all_surfaces_report_one_task_by_default():
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            real, _ = await _seed_mixed(conn, owner)
            assert [t["id"] for t in await visible_tasks(conn, owner)] == [real]
            assert [t["id"] for t in await search_active_tasks_for_delete(conn, owner, "persona")] == []
            assert [t["id"] for t in await search_active_tasks_for_delete(conn, owner, "essay")] == [real]
            assert [t["id"] for t in await list_nearest_active_titles(conn, owner)] == [real]
            assert [t["id"] for t in await get_all_active_tasks_for_user(conn, owner)] == [real]
            # An explicit numeric id may not reach a demo row unless demo is requested
            demo_id = await conn.fetchval(
                "SELECT id FROM tasks WHERE user_id=$1 AND title LIKE 'Persona%' LIMIT 1", owner
            )
            assert await search_active_tasks_for_delete(conn, owner, str(demo_id)) == []
        assert await _dashboard_ids(owner, include_demo=False) == [str(real)]
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
async def test_all_surfaces_report_five_tasks_with_include_demo():
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            await _seed_mixed(conn, owner)
            assert len(await visible_tasks(conn, owner, include_demo=True)) == 5
            assert len(await search_active_tasks_for_delete(conn, owner, "persona", include_demo=True)) == 4
            assert len(await list_nearest_active_titles(conn, owner, limit=10, include_demo=True)) == 5
            assert len(await get_all_active_tasks_for_user(conn, owner, include_demo=True)) == 5
            demo_id = await conn.fetchval(
                "SELECT id FROM tasks WHERE user_id=$1 AND title LIKE 'Persona%' LIMIT 1", owner
            )
            assert len(await search_active_tasks_for_delete(conn, owner, str(demo_id), include_demo=True)) == 1
        assert len(await _dashboard_ids(owner, include_demo=True)) == 5
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
async def test_other_tenants_never_leak_and_owner_is_required():
    pool = await get_pool()
    owner_a, owner_b = _tenant("a"), _tenant("b")
    try:
        async with pool.acquire() as conn:
            real_a, _ = await _seed_mixed(conn, owner_a)
            real_b = await _insert(conn, owner_b, "Tenant B secret essay")
            for demo in (False, True):
                ids_a = {t["id"] for t in await visible_tasks(conn, owner_a, include_demo=demo)}
                assert real_b not in ids_a and real_a in ids_a
                found = await search_active_tasks_for_delete(conn, owner_a, "essay", include_demo=demo)
                assert real_b not in {t["id"] for t in found}
                nearest = await list_nearest_active_titles(conn, owner_a, limit=50, include_demo=demo)
                assert real_b not in {t["id"] for t in nearest}
                every = await get_all_active_tasks_for_user(conn, owner_a, include_demo=demo)
                assert real_b not in {t["id"] for t in every}
                assert await search_active_tasks_for_delete(conn, owner_a, str(real_b), include_demo=demo) == []
            for bad in (None, "", "   "):
                with pytest.raises(ValueError):
                    await visible_tasks(conn, bad)
    finally:
        await _cleanup(pool, owner_a, owner_b)


@pytest.mark.asyncio
async def test_chat_task_handlers_require_an_owner_and_hide_demo():
    from backend.skills.handlers.tasks import handle_query_tasks

    pool = await get_pool()
    owner, other = _tenant("a"), _tenant("b")
    try:
        async with pool.acquire() as conn:
            await _seed_mixed(conn, owner)
            await _insert(conn, other, "Other tenant task")
        res = await handle_query_tasks({}, pool)
        assert "Other tenant task" not in str(res)
        hidden = await handle_query_tasks({"user_id": owner}, pool)
        assert "Persona item" not in str(hidden) and "Real essay draft" in str(hidden)
        shown = await handle_query_tasks({"user_id": owner, "include_demo": True}, pool)
        assert "Persona item" in str(shown)
    finally:
        await _cleanup(pool, owner, other)


def test_demo_sql_predicate_shape():
    assert demo_sql_predicate() == "(COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%')"
    assert demo_sql_predicate("t").startswith("(COALESCE(t.trusted_event_url,'')")


# ---- chat delete flow through the orchestrator -------------------------------------


async def _say(owner, message, **kwargs):
    return await handle_message(conversation_id=f"conv-{owner}", message=message, user_id=owner, **kwargs)


async def _deleted_count(pool, owner):
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND deleted_at IS NOT NULL", owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["delete test", "delete my deadline", "delete my overdue deadline"])
async def test_single_visible_match_stages_a_delete_card(message):
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            real = await _insert(conn, owner, "test", due=date.today() - timedelta(days=3))
            for slug in DEMO_SLUGS:  # demo rows must not make this ambiguous
                await _insert(conn, owner, f"test demo {slug}", url=f"compass://demo-persona/{slug}")
        res = await _say(owner, message)
        pending = res["data"]["pending_action"]
        assert res["skill_used"] == "chat_delete_task"
        assert pending["action"] == "delete_task"
        assert pending["task_ids"] == [real]
        assert await _deleted_count(pool, owner) == 0
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
async def test_overdue_single_match_among_future_and_completed_tasks():
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            late = await _insert(conn, owner, "late report", due=date.today() - timedelta(days=2))
            await _insert(conn, owner, "future report", due=date.today() + timedelta(days=9))
            await _insert(conn, owner, "done report", due=date.today() - timedelta(days=5), status="done")
        res = await _say(owner, "delete my overdue deadline")
        pending = res["data"]["pending_action"]
        assert pending["action"] == "delete_task"
        assert pending["task_ids"] == [late]
        assert await _deleted_count(pool, owner) == 0
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["delete test", "delete my deadline", "delete my overdue deadline"])
async def test_two_matches_stage_a_disambiguation_and_change_nothing(message):
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            real, _ = await _seed_mixed(conn, owner)
            first = await _insert(conn, owner, "test", due=date.today() - timedelta(days=3))
            second = await _insert(conn, owner, "test two", due=date.today() - timedelta(days=1))
        res = await _say(owner, message)
        pending = res["data"]["pending_action"]
        assert pending["action"] == "delete_task_disambiguation"
        expected = [first, second] if message != "delete my deadline" else [real, first, second]
        assert sorted(pending["task_ids"]) == sorted(expected)
        assert "1. '" in res["response"] and "2. '" in res["response"]
        assert "Persona item" not in res["response"]
        assert await _deleted_count(pool, owner) == 0
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
async def test_no_match_lists_only_visible_tasks_unless_demo_requested():
    pool = await get_pool()
    owner = _tenant()
    try:
        async with pool.acquire() as conn:
            await _seed_mixed(conn, owner)
        res = await _say(owner, "delete zebra crossing")
        assert "Real essay draft" in res["response"] and "Persona item" not in res["response"]
        res_demo = await _say(owner, "delete zebra crossing", include_demo=True)
        assert "Persona item" in res_demo["response"]
        # Overdue with nothing overdue stages nothing
        res_none = await _say(owner, "delete my overdue deadline")
        assert "pending_action" not in (res_none["data"] or {})
        assert "Persona item" not in res_none["response"]
        assert await _deleted_count(pool, owner) == 0
    finally:
        await _cleanup(pool, owner)


# ---- parse_delete_target ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my overdue deadline", DeleteTarget("", True, "overdue")),
        ("overdue", DeleteTarget("", True, "overdue")),
        ("the OVERDUE hackathon task", DeleteTarget("hackathon", False, "overdue")),
        ("my completed tasks", DeleteTarget("", True, "completed")),
        ("done", DeleteTarget("", True, "completed")),
        ("a done math lab", DeleteTarget("math lab", False, "completed")),
        ("my deadline", DeleteTarget("", True, None)),
        ("Please the Reminder", DeleteTarget("", True, None)),
        ("the hackathon task", DeleteTarget("hackathon", False, None)),
        ("42", DeleteTarget("42", False, None)),
        ("", DeleteTarget("", True, None)),
        (None, DeleteTarget("", True, None)),
    ],
)
def test_parse_delete_target(raw, expected):
    assert parse_delete_target(raw) == expected


def test_parse_delete_target_keeps_normalize_contract_and_is_linear():
    assert normalize_delete_target("my overdue deadline") == ("overdue", False)
    assert parse_delete_target("overdue " * 50000) == DeleteTarget("", True, "overdue")
