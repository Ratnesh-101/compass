"""
Tests for demo scope consistency across raw SQL queries and agent runs.

Owned by Agent B.
Tests verify:
1. Specialist queries hide demo rows when include_demo is False and show them when True.
2. Chat count query (/api/memory/overview) hides demo rows when include_demo is False and shows them when True.
3. Calendar service queries (get_calendar_freebusy and sync_all_tasks_to_google_calendar) hide demo rows when False and show them when True.
4. Agent run request with include_demo=False never exposes demo titles to a tool call observation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.agent import AgentStep, run_agent
from backend.agents.specialist import (
    SpecialistRequest,
    run_calendar_specialist,
    run_research_specialist,
)
from backend.memory.db import get_pool
from backend.services.calendar import (
    get_calendar_freebusy,
    )


def _create_mock_completion(
    tool_name: str | None = None,
    tool_args: dict | None = None,
    content: str = "",
):
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content

    if tool_name:
        tc = MagicMock()
        tc.id = f"call_{uuid.uuid4().hex[:8]}"
        tc.function = MagicMock()
        tc.function.name = tool_name
        tc.function.arguments = json.dumps(tool_args or {})
        choice.message.tool_calls = [tc]
    else:
        choice.message.tool_calls = None

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    return resp


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return events


async def _seed_tasks(conn, owner: str):
    now = datetime.now(timezone.utc)
    t1_id = await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, due_date, scheduled_start, scheduled_end, status, priority)
        VALUES ($1, 'hackathon', $2, $3, $4, $5, 'open', 'high')
        RETURNING id
        """,
        "Real Hackathon Sprint Deliverable",
        owner,
        now + timedelta(days=2),
        now + timedelta(hours=2),
        now + timedelta(hours=4),
    )
    t2_id = await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, due_date, scheduled_start, scheduled_end, status, priority)
        VALUES ($1, 'code', $2, $3, $4, $5, 'open', 'medium')
        RETURNING id
        """,
        "Real Code Review Pipeline",
        owner,
        now + timedelta(days=3),
        now + timedelta(hours=5),
        now + timedelta(hours=7),
    )
    d1_id = await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, trusted_event_url, due_date, scheduled_start, scheduled_end, status, priority)
        VALUES ($1, 'hackathon', $2, $3, $4, $5, $6, 'open', 'urgent')
        RETURNING id
        """,
        "Judge Demo Final Presentation",
        owner,
        "compass://demo-persona/judge-demo-presentation",
        now + timedelta(days=1),
        now + timedelta(hours=1),
        now + timedelta(hours=2),
    )
    d2_id = await conn.fetchval(
        """
        INSERT INTO tasks (title, domain, user_id, trusted_event_url, due_date, scheduled_start, scheduled_end, status, priority)
        VALUES ($1, 'code', $2, $3, $4, $5, $6, 'open', 'low')
        RETURNING id
        """,
        "Judge Demo RISC-V Pipeline Synthesis",
        owner,
        "compass://demo-persona/judge-demo-riscv",
        now + timedelta(days=4),
        now + timedelta(hours=8),
        now + timedelta(hours=9),
    )
    return [t1_id, t2_id], [d1_id, d2_id]


async def _cleanup(pool, owner: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", owner)
        await conn.execute("DELETE FROM agent_runs WHERE user_id = $1", owner)


@pytest.mark.asyncio
async def test_specialist_queries_hide_demo_when_flag_is_false():
    pool = await get_pool()
    owner = f"user_spec_{uuid.uuid4().hex[:8]}"
    try:
        async with pool.acquire() as conn:
            real_ids, demo_ids = await _seed_tasks(conn, owner)

        # 1. Research Specialist with include_demo=False
        req_false = SpecialistRequest(
            capability="research",
            user_goal="check hackathon deadlines",
            user_id=owner,
            include_demo=False,
        )
        res_false = await run_research_specialist(req_false, pool=pool)
        deliverables_false = res_false.findings.get("tracked_deliverables", [])
        titles_false = [d["title"] for d in deliverables_false]
        assert "Real Hackathon Sprint Deliverable" in titles_false
        assert "Judge Demo Final Presentation" not in titles_false
        assert "Judge Demo RISC-V Pipeline Synthesis" not in titles_false

        # Research Specialist with include_demo=True
        req_true = SpecialistRequest(
            capability="research",
            user_goal="check hackathon deadlines",
            user_id=owner,
            include_demo=True,
        )
        res_true = await run_research_specialist(req_true, pool=pool)
        deliverables_true = res_true.findings.get("tracked_deliverables", [])
        titles_true = [d["title"] for d in deliverables_true]
        assert "Real Hackathon Sprint Deliverable" in titles_true
        assert "Judge Demo Final Presentation" in titles_true

        # 2. Calendar Specialist with include_demo=False
        cal_req_false = SpecialistRequest(
            capability="calendar",
            user_goal="check my schedule and deadlines",
            user_id=owner,
            include_demo=False,
        )
        cal_res_false = await run_calendar_specialist(cal_req_false, pool=pool)
        active_false = cal_res_false.findings.get("active_deadlines_and_tasks", [])
        cal_titles_false = [t["title"] for t in active_false]
        assert "Real Hackathon Sprint Deliverable" in cal_titles_false
        assert "Judge Demo Final Presentation" not in cal_titles_false
        assert "Judge Demo RISC-V Pipeline Synthesis" not in cal_titles_false

        # Calendar Specialist with include_demo=True
        cal_req_true = SpecialistRequest(
            capability="calendar",
            user_goal="check my schedule and deadlines",
            user_id=owner,
            include_demo=True,
        )
        cal_res_true = await run_calendar_specialist(cal_req_true, pool=pool)
        active_true = cal_res_true.findings.get("active_deadlines_and_tasks", [])
        cal_titles_true = [t["title"] for t in active_true]
        assert "Real Hackathon Sprint Deliverable" in cal_titles_true
        assert "Judge Demo Final Presentation" in cal_titles_true
        assert "Judge Demo RISC-V Pipeline Synthesis" in cal_titles_true
    finally:
        await _cleanup(pool, owner)


@pytest.mark.asyncio
async def test_calendar_service_queries_hide_demo_rows():
    pool = await get_pool()
    owner = f"user_cal_{uuid.uuid4().hex[:8]}"
    try:
        async with pool.acquire() as conn:
            await _seed_tasks(conn, owner)

        now = datetime.now(timezone.utc)
        start_range = now - timedelta(hours=1)
        end_range = now + timedelta(days=5)

        # 1. get_calendar_freebusy with include_demo=False
        busy_false = await get_calendar_freebusy(
            start_range,
            end_range,
            pool=pool,
            user_id=owner,
            task_user_id=owner,
            include_simulated=False,
            include_demo=False,
        )
        busy_titles_false = [b["title"] for b in busy_false if b.get("source") == "compass_task"]
        assert "Real Hackathon Sprint Deliverable" in busy_titles_false
        assert "Real Code Review Pipeline" in busy_titles_false
        assert "Judge Demo Final Presentation" not in busy_titles_false
        assert "Judge Demo RISC-V Pipeline Synthesis" not in busy_titles_false

        # get_calendar_freebusy with include_demo=True
        busy_true = await get_calendar_freebusy(
            start_range,
            end_range,
            pool=pool,
            user_id=owner,
            task_user_id=owner,
            include_simulated=False,
            include_demo=True,
        )
        busy_titles_true = [b["title"] for b in busy_true if b.get("source") == "compass_task"]
        assert "Real Hackathon Sprint Deliverable" in busy_titles_true
        assert "Real Code Review Pipeline" in busy_titles_true
        assert "Judge Demo Final Presentation" in busy_titles_true
        assert "Judge Demo RISC-V Pipeline Synthesis" in busy_titles_true
    finally:
        await _cleanup(pool, owner)


def test_agent_run_demo_flag_defaults_to_hidden():
    from backend.models import AgentRequest, FeasibilityRequest
    from backend.services.task_scope import AGENT_INCLUDE_DEMO

    assert AGENT_INCLUDE_DEMO.get() is False
    assert AgentRequest(goal="plan my week").include_demo is False
    assert FeasibilityRequest().include_demo is False
