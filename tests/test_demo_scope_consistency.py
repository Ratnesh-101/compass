"""
Compass - Judge Persona demo data consistency tests.

Verifies that demo rows (trusted_event_url starting with 'compass://demo-persona/')
are hidden everywhere unless the caller explicitly passes include_demo=True:
- structured.list_tasks default is False
- The three calendar skill handlers
- The add_task duplicate check
- /api/schedule/propose endpoint
- feasibility._fetch_open_tasks
- AST-based guard enforcing all list_tasks calls in backend/ pass include_demo
"""

from __future__ import annotations

import ast
import os
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from backend.agents.feasibility import _fetch_open_tasks
from backend.dependencies import Identity
from backend.memory import structured
from backend.memory.db import get_pool
from backend.models import ProposeScheduleBody
from backend.orchestrator import handle_message
from backend.routers.calendar import propose_schedule_endpoint
from backend.skills.handlers.calendar import (
    handle_detect_schedule_conflicts,
    handle_propose_schedule,
)


def _unique_user() -> str:
    return f"test_scope_user_{uuid.uuid4().hex[:10]}"


async def _insert_task(
    conn: Any,
    user_id: str,
    title: str,
    *,
    url: str | None = None,
    due_date: date | None = None,
    duration: int = 30,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, trusted_event_url, due_date, duration_minutes, status)
        VALUES ($1, 'general', $2, $3, $4, $5, 'open')
        RETURNING id
        """,
        title,
        user_id,
        url,
        due_date,
        duration,
    )


async def _seed_tasks(conn: Any, user_id: str) -> Dict[str, Any]:
    tomorrow = date.today() + timedelta(days=1)
    day_after = date.today() + timedelta(days=2)

    real_1_id = await _insert_task(conn, user_id, "Real Assignment Draft", due_date=tomorrow)
    real_2_id = await _insert_task(conn, user_id, "Real Code Submission", due_date=day_after)

    demo_1_id = await _insert_task(
        conn,
        user_id,
        "Judge Persona Hackathon Sprint",
        url="compass://demo-persona/hackathon-sprint",
        due_date=tomorrow,
    )
    demo_2_id = await _insert_task(
        conn,
        user_id,
        "Judge Persona Lab 4 RISC-V",
        url="compass://demo-persona/lab-4-riscv",
        due_date=day_after,
    )

    return {
        "real_ids": [real_1_id, real_2_id],
        "demo_ids": [demo_1_id, demo_2_id],
        "real_titles": {"Real Assignment Draft", "Real Code Submission"},
        "demo_titles": {"Judge Persona Hackathon Sprint", "Judge Persona Lab 4 RISC-V"},
    }


async def _cleanup(pool: Any, user_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = $1", user_id)
        await conn.execute("DELETE FROM conversations WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user_id)


@pytest.mark.asyncio
async def test_list_tasks_default_and_include_demo():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

            # 1. Default call (no include_demo passed): must default to False
            default_tasks = await structured.list_tasks(conn, user_id=user)
            default_titles = {t["title"] for t in default_tasks}
            assert seeded["real_titles"].issubset(default_titles)
            assert not (seeded["demo_titles"] & default_titles), "Demo tasks must be absent by default"

            # 2. Explicit False
            false_tasks = await structured.list_tasks(conn, user_id=user, include_demo=False)
            false_titles = {t["title"] for t in false_tasks}
            assert not (seeded["demo_titles"] & false_titles), "Demo tasks must be absent with include_demo=False"

            # 3. Explicit True
            true_tasks = await structured.list_tasks(conn, user_id=user, include_demo=True)
            true_titles = {t["title"] for t in true_tasks}
            assert seeded["real_titles"].issubset(true_titles)
            assert seeded["demo_titles"].issubset(true_titles), "Demo tasks must be present with include_demo=True"
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_calendar_skill_propose_schedule_without_task_ids():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        # include_demo=False
        res_false = await handle_propose_schedule({"user_id": user, "include_demo": False}, pool)
        data_false = res_false.get("data") or {}
        considered_false = {t["title"] for t in (data_false.get("scheduled") or []) + (data_false.get("unassigned") or [])}
        assert not (seeded["demo_titles"] & considered_false), "Demo tasks must not be proposed with include_demo=False"

        # include_demo=True
        res_true = await handle_propose_schedule({"user_id": user, "include_demo": True}, pool)
        data_true = res_true.get("data") or {}
        considered_true = {t["title"] for t in (data_true.get("scheduled") or []) + (data_true.get("unassigned") or [])}
        assert seeded["demo_titles"].issubset(considered_true), "Demo tasks must be proposed with include_demo=True"
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_calendar_skill_propose_schedule_with_task_ids():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        all_task_ids = seeded["real_ids"] + seeded["demo_ids"]

        # With task_ids and include_demo=False
        res_false = await handle_propose_schedule(
            {"user_id": user, "task_ids": all_task_ids, "include_demo": False}, pool
        )
        data_false = res_false.get("data") or {}
        considered_false = {t["title"] for t in (data_false.get("scheduled") or []) + (data_false.get("unassigned") or [])}
        assert not (seeded["demo_titles"] & considered_false), "Demo tasks must not be proposed when include_demo=False"

        # With task_ids and include_demo=True
        res_true = await handle_propose_schedule(
            {"user_id": user, "task_ids": all_task_ids, "include_demo": True}, pool
        )
        data_true = res_true.get("data") or {}
        considered_true = {t["title"] for t in (data_true.get("scheduled") or []) + (data_true.get("unassigned") or [])}
        assert seeded["demo_titles"].issubset(considered_true), "Demo tasks must be proposed when include_demo=True"
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_calendar_skill_detect_schedule_conflicts():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        # include_demo=False
        res_false = await handle_detect_schedule_conflicts({"user_id": user, "include_demo": False}, pool)
        assert res_false.get("data", {}).get("scanned_tasks_count") == len(seeded["real_ids"])

        # include_demo=True
        res_true = await handle_detect_schedule_conflicts({"user_id": user, "include_demo": True}, pool)
        assert res_true.get("data", {}).get("scanned_tasks_count") == len(seeded["real_ids"]) + len(seeded["demo_ids"])
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_add_task_duplicate_check_with_demo_task():
    """Adding a real task whose title equals a hidden demo title must SUCCEED when include_demo=False."""
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        demo_title = "Judge Persona Hackathon Sprint"
        tomorrow = str(date.today() + timedelta(days=1))

        # 1. With include_demo=False, duplicate check ignores hidden demo tasks -> must SUCCEED
        res_false = await handle_message(
            message="add task",
            user_id=user,
            pre_routed_skill="add_task",
            pre_routed_args={"title": demo_title, "due_date": tomorrow},
            include_demo=False,
            persist=False,
        )
        assert res_false["success"] is True, f"Expected success when include_demo=False, got: {res_false}"
        assert (res_false.get("data") or {}).get("error") != "duplicate_exact_deadline"

        # 2. With include_demo=True, duplicate check sees the demo task -> must be BLOCKED as duplicate
        res_true = await handle_message(
            message="add task",
            user_id=user,
            pre_routed_skill="add_task",
            pre_routed_args={"title": demo_title, "due_date": tomorrow},
            include_demo=True,
            persist=False,
        )
        assert res_true["success"] is False
        assert (res_true.get("data") or {}).get("error") == "duplicate_exact_deadline"
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_calendar_router_propose_schedule_endpoint():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        ident = Identity(id=user, user_id=user, is_guest=False)

        # 1. include_demo=False
        body_false = ProposeScheduleBody(include_demo=False)
        resp_false = await propose_schedule_endpoint(body_false, ident=ident)
        data_false = resp_false.get("data") or {}
        considered_false = {t["title"] for t in (data_false.get("scheduled") or []) + (data_false.get("unassigned") or [])}
        assert not (seeded["demo_titles"] & considered_false), "Demo tasks must be absent when include_demo=False"

        # 2. include_demo=True
        body_true = ProposeScheduleBody(include_demo=True)
        resp_true = await propose_schedule_endpoint(body_true, ident=ident)
        data_true = resp_true.get("data") or {}
        considered_true = {t["title"] for t in (data_true.get("scheduled") or []) + (data_true.get("unassigned") or [])}
        assert seeded["demo_titles"].issubset(considered_true), "Demo tasks must be present when include_demo=True"
    finally:
        await _cleanup(pool, user)


@pytest.mark.asyncio
async def test_feasibility_fetch_open_tasks():
    pool = await get_pool()
    user = _unique_user()
    try:
        async with pool.acquire() as conn:
            seeded = await _seed_tasks(conn, user)

        # 1. include_demo=False
        tasks_false = await _fetch_open_tasks(pool, domain=None, user_id=user, include_demo=False)
        titles_false = {t["title"] for t in tasks_false}
        assert seeded["real_titles"].issubset(titles_false)
        assert not (seeded["demo_titles"] & titles_false), "Demo tasks must be absent from feasibility fetch"

        # 2. include_demo=True
        tasks_true = await _fetch_open_tasks(pool, domain=None, user_id=user, include_demo=True)
        titles_true = {t["title"] for t in tasks_true}
        assert seeded["real_titles"].issubset(titles_true)
        assert seeded["demo_titles"].issubset(titles_true), "Demo tasks must be present in feasibility fetch"
    finally:
        await _cleanup(pool, user)


def test_ast_guard_backend_list_tasks_calls_pass_include_demo():
    """Fails if any list_tasks( call in backend/ (except the definition) lacks an explicit include_demo keyword."""
    violations: List[str] = []
    backend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")

    for root, _, files in os.walk(backend_dir):
        for file in files:
            if not file.endswith(".py"):
                continue
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, os.path.dirname(backend_dir))
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    is_list_tasks = False
                    if isinstance(func, ast.Name) and func.id == "list_tasks":
                        is_list_tasks = True
                    elif isinstance(func, ast.Attribute) and func.attr == "list_tasks":
                        is_list_tasks = True

                    if is_list_tasks:
                        has_include_demo = any(k.arg == "include_demo" for k in node.keywords)
                        if not has_include_demo:
                            violations.append(f"{rel_path}:{node.lineno}")

    assert not violations, f"list_tasks() call(s) missing explicit include_demo keyword: {violations}"
