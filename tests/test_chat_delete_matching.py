"""
Compass — chat delete target matching.

"delete my deadline" / "delete the task" / "delete my tasks" must not be searched as
literal titles. Generic targets stage a card for the only task, or list candidates;
specific targets match by title. Nothing is ever deleted before confirmation and
never more than one task per message.
"""

from __future__ import annotations

import os

import pytest

from backend.memory.db import get_pool
from backend.orchestrator import handle_message
from backend.services.delete_target import normalize_delete_target


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my deadline", ("", True)),
        ("the task", ("", True)),
        ("my tasks", ("", True)),
        ("Please the Reminder", ("", True)),
        ("test", ("test", False)),
        ("the hackathon task", ("hackathon", False)),
        ("This  Math   Lab", ("math lab", False)),
        ("42", ("42", False)),
        ("", ("", True)),
    ],
)
def test_normalize_delete_target(raw, expected):
    assert normalize_delete_target(raw) == expected


def test_normalize_delete_target_is_linear_on_hostile_input():
    assert normalize_delete_target("my " * 50000) == ("", True)
    specific, generic = normalize_delete_target("x " * 50000)
    assert generic is False and len(specific) <= 200


@pytest.fixture(autouse=True)
def ensure_real_postgres():
    test_db = os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not test_db:
        pytest.skip("DATABASE_URL / TEST_DATABASE_URL not set; skipping chat delete matching suite.")


USER = "test_user_delete_matching"
OTHER = "test_user_delete_matching_other"
CONV = "conv-delete-matching"


async def _seed(titles, user=USER):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity IN ($1, $2)", USER, OTHER)
        await conn.execute("DELETE FROM tasks WHERE user_id IN ($1, $2)", USER, OTHER)
        ids = []
        for title in titles:
            ids.append(
                await conn.fetchval(
                    "INSERT INTO tasks (title, domain, user_id) VALUES ($1, 'general', $2) RETURNING id",
                    title,
                    user,
                )
            )
    return pool, ids


async def _snapshot(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, deleted_at FROM tasks WHERE user_id IN ($1, $2) ORDER BY id", USER, OTHER
        )
    return [(r["id"], r["deleted_at"]) for r in rows]


async def _cleanup(pool):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity IN ($1, $2)", USER, OTHER)
        await conn.execute("DELETE FROM tasks WHERE user_id IN ($1, $2)", USER, OTHER)


async def _say(message, user=USER):
    return await handle_message(conversation_id=CONV, message=message, user_id=user)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["delete test", "delete my deadline", "delete the task", "delete my tasks"])
async def test_single_task_stages_a_card_without_deleting(message):
    pool, ids = await _seed(["test"])
    try:
        before = await _snapshot(pool)
        res = await _say(message)
        assert res["skill_used"] == "chat_delete_task"
        pending = res["data"]["pending_action"]
        assert pending["action"] == "delete_task"
        assert pending["task_ids"] == ids
        assert "Are you sure you want to delete task 'test'" in res["response"]
        assert await _snapshot(pool) == before
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["delete my deadline", "delete my tasks", "delete the task"])
async def test_several_tasks_generic_target_stages_nothing_and_lists_candidates(message):
    pool, ids = await _seed(["test", "hackathon pitch"])
    try:
        before = await _snapshot(pool)
        res = await _say(message)
        assert res["skill_used"] == "chat_delete_task"
        assert "Which one" in res["response"]
        assert "1. 'test'" in res["response"] or "1. 'hackathon pitch'" in res["response"]
        assert "'test'" in res["response"] and "'hackathon pitch'" in res["response"]
        pending = res["data"]["pending_action"]
        assert pending["action"] == "delete_task_disambiguation"
        assert sorted(pending["task_ids"]) == sorted(ids)
        assert await _snapshot(pool) == before
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_specific_target_stages_only_the_matching_task():
    pool, ids = await _seed(["test", "hackathon pitch"])
    try:
        before = await _snapshot(pool)
        res = await _say("delete the hackathon task")
        pending = res["data"]["pending_action"]
        assert pending["action"] == "delete_task"
        assert pending["task_ids"] == [ids[1]]
        res2 = await _say("delete TEST")
        assert res2["data"]["pending_action"]["task_ids"] == [ids[0]]
        assert await _snapshot(pool) == before
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_specific_target_matching_several_lists_candidates():
    pool, ids = await _seed(["Review Math Lab 1", "Review Math Lab 2", "Essay"])
    try:
        res = await _say("delete math")
        assert "Found 2 tasks matching 'math'" in res["response"]
        assert res["data"]["pending_action"]["action"] == "delete_task_disambiguation"
        assert sorted(res["data"]["pending_action"]["task_ids"]) == sorted(ids[:2])
        assert all(d is None for _, d in await _snapshot(pool))
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_no_match_lists_nearest_titles_and_never_echoes_the_phrase():
    pool, _ = await _seed(["test", "hackathon pitch"])
    try:
        before = await _snapshot(pool)
        res = await _say("delete zebra crossing")
        assert "zebra" not in res["response"].lower()
        assert "'test'" in res["response"] and "'hackathon pitch'" in res["response"]
        assert "pending_action" not in (res["data"] or {})
        assert await _snapshot(pool) == before
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_no_tasks_says_nothing_to_delete():
    pool, _ = await _seed([])
    try:
        for message in ("delete my deadline", "delete my tasks"):
            res = await _say(message)
            assert res["response"] == "You have no active tasks to delete."
            assert "pending_action" not in (res["data"] or {})
        assert await _snapshot(pool) == []
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_many_tasks_offers_at_most_three_and_deletes_nothing():
    pool, _ = await _seed([f"task item {i}" for i in range(6)])
    try:
        res = await _say("delete my tasks")
        assert len(res["data"]["pending_action"]["task_ids"]) == 3
        assert "first 3 of 6" in res["response"]
        assert all(d is None for _, d in await _snapshot(pool))
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_confirm_deletes_exactly_one_task():
    pool, ids = await _seed(["test", "hackathon pitch"])
    try:
        await _say("delete my deadline")
        await _say("2")
        deleted = [tid for tid, d in await _snapshot(pool) if d is not None]
        assert deleted == [ids[1]]
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_wildcards_in_the_target_are_matched_literally():
    pool, _ = await _seed(["test", "hackathon pitch"])
    try:
        res = await _say("delete t%t")
        assert "pending_action" not in (res["data"] or {})
        res = await _say("delete h_ckathon")
        assert "pending_action" not in (res["data"] or {})
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_other_users_tasks_are_never_listed_or_matched():
    pool, _ = await _seed(["secret roadmap"], user=OTHER)
    try:
        before = await _snapshot(pool)
        for message in ("delete my deadline", "delete secret roadmap", "delete my tasks"):
            res = await _say(message)
            assert "secret" not in res["response"].lower()
            assert "pending_action" not in (res["data"] or {})
        assert await _snapshot(pool) == before
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_reply_three_with_two_candidates_is_safe():
    pool, _ = await _seed(["test", "hackathon pitch"])
    try:
        await _say("delete my deadline")
        res = await _say("3")
        assert res["success"] is False
        assert "Which one" in res["response"]
        assert all(d is None for _, d in await _snapshot(pool))
        res = await _say("confirm")
        assert all(d is None for _, d in await _snapshot(pool)), "unclear reply must not default to candidate 1"
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["2", "3", "second one"])
async def test_ordinal_reply_never_confirms_a_single_delete_card(reply):
    pool, _ = await _seed(["test"])
    try:
        await _say("delete test")
        res = await _say(reply)
        assert "isn't a confirmation" in res["response"]
        assert all(d is None for _, d in await _snapshot(pool))
        await _say("confirm")
        assert all(d is not None for _, d in await _snapshot(pool))
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_title_containing_generic_words_still_matches():
    pool, ids = await _seed(["Fix deadline bug", "Write essay"])
    try:
        res = await _say("delete fix deadline bug")
        assert res["data"]["pending_action"]["task_ids"] == [ids[0]]
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_percent_and_underscore_in_real_titles_match_literally():
    pool, ids = await _seed(["100% complete", "snake_case cleanup", "plain"])
    try:
        assert (await _say("delete 100%"))["data"]["pending_action"]["task_ids"] == [ids[0]]
        assert (await _say("delete snake_case"))["data"]["pending_action"]["task_ids"] == [ids[1]]
    finally:
        await _cleanup(pool)


@pytest.mark.asyncio
async def test_soft_deleted_tasks_are_excluded_from_matches_and_suggestions():
    pool, ids = await _seed(["gone task", "kept task"])
    try:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE tasks SET deleted_at = now() WHERE id = $1", ids[0])
        res = await _say("delete gone")
        assert "gone" not in res["response"].lower()
        res = await _say("delete my deadline")
        assert res["data"]["pending_action"]["task_ids"] == [ids[1]]
    finally:
        await _cleanup(pool)
