"""
Comprehensive Test Suite for Output Token Budgets, Response Truncation Handling,
Tavily Verification Intent & Rigor, Dynamic Date Integrity, and Deadline Intelligence.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.config import get_settings
from backend.router_helpers import (
    is_tavily_verification_intent,
    extract_verification_target,
)
from backend.agent_types import _build_agent_system_prompt
from backend.agent_synthesis import force_final_synthesis
from backend.skills.schemas_web import VERIFY_WITH_TAVILY_TOOL, VERIFY_DEADLINE_TOOL
from backend.skills.handlers.web import handle_verify_with_tavily


# ============================================================================
# 1. OUTPUT LIMITS & CONFIGURATION
# ============================================================================

def test_configured_output_budgets_exist():
    """1-3. Verify configurable output token budgets and defaults."""
    settings = get_settings()
    assert hasattr(settings, "MAX_DEFAULT_OUTPUT_TOKENS")
    assert hasattr(settings, "MAX_SYNTHESIS_TOKENS")
    assert hasattr(settings, "MAX_REASONING_TOKENS")
    assert hasattr(settings, "MAX_CONTINUATION_ATTEMPTS")

    assert settings.MAX_DEFAULT_OUTPUT_TOKENS == 4096
    assert settings.MAX_SYNTHESIS_TOKENS == 8192
    assert settings.MAX_REASONING_TOKENS == 4096
    assert settings.MAX_CONTINUATION_ATTEMPTS == 2


@pytest.mark.asyncio
async def test_synthesis_budget_passed_and_bounded_continuation():
    """4-8. Synthesis receives MAX_SYNTHESIS_TOKENS and performs bounded continuation on finish_reason=length."""
    settings = get_settings()
    mock_client = MagicMock()

    # First chunk response: cut off with finish_reason="length"
    first_choice = MagicMock()
    first_choice.message.content = "Here is part 1 of the comprehensive report: | Item | Date | Prize |\n| Hackathon A | Oct 2026 | $50k |"
    first_choice.finish_reason = "length"
    first_resp = MagicMock()
    first_resp.choices = [first_choice]
    first_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=400)

    # Second chunk response: completes normally
    second_choice = MagicMock()
    second_choice.message.content = "\n| Hackathon B | Nov 2026 | $30k |\nConclusion of report."
    second_choice.finish_reason = "stop"
    second_resp = MagicMock()
    second_resp.choices = [second_choice]
    second_resp.usage = MagicMock(prompt_tokens=200, completion_tokens=100)

    mock_client.chat.completions.create = AsyncMock(side_effect=[first_resp, second_resp])

    messages = [{"role": "user", "content": "Find open hackathons"}]

    step, cost, is_abstained = await force_final_synthesis(
        client=mock_client,
        settings=settings,
        messages=messages,
        step_num=3,
        start_time=1000.0,
        run_id="run-123",
        active_replan_diff=None,
    )

    assert mock_client.chat.completions.create.call_count == 2
    # Verify first call used MAX_SYNTHESIS_TOKENS
    first_call_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
    assert first_call_kwargs["max_tokens"] == settings.MAX_SYNTHESIS_TOKENS

    # Content from both calls assembled without loss
    assert "Here is part 1" in step.content
    assert "Hackathon B" in step.content
    assert step.metadata is not None
    assert step.metadata["finish_reason"] == "stop"
    assert step.metadata["continuation_attempts"] == 1
    assert step.metadata["is_truncated"] is False


@pytest.mark.asyncio
async def test_continuation_attempts_are_bounded_at_max():
    """8. Truncated synthesis stops at MAX_CONTINUATION_ATTEMPTS and flags is_truncated."""
    settings = get_settings()
    mock_client = MagicMock()

    # Always cut off with finish_reason="length"
    choice = MagicMock()
    choice.message.content = "\nContinuing unending tokens..."
    choice.finish_reason = "length"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=400)

    mock_client.chat.completions.create = AsyncMock(return_value=resp)

    messages = [{"role": "user", "content": "Long report"}]

    step, cost, is_abstained = await force_final_synthesis(
        client=mock_client,
        settings=settings,
        messages=messages,
        step_num=4,
        start_time=1000.0,
        run_id="run-456",
        active_replan_diff=None,
    )

    # Initial call (1) + MAX_CONTINUATION_ATTEMPTS (2) = 3 calls total
    assert mock_client.chat.completions.create.call_count == 3
    assert step.metadata is not None
    assert step.metadata["is_truncated"] is True
    assert step.metadata["continuation_attempts"] == 2
    # Requirement 4: NO closing markdown to fake completeness; preserve intact partial text
    assert "maximum token budget" not in step.content
    assert "Continuing unending tokens..." in step.content


# ============================================================================
# 2. TAVILY VERIFICATION INTENT & EXTRACTION
# ============================================================================

def test_tavily_verification_intent_phrases():
    """13. Explicit verification phrases trigger verification intent."""
    valid_intents = [
        "Verify it with Tavily.",
        "Verify this with Tavily",
        "Check this deadline with Tavily",
        "Fact-check this answer using Tavily",
        "Can you verify with Tavily?",
        "Please fact-check this with tavily",
        "verify with tavily",
        "Verify the registration deadline using tavily",
    ]
    for phrase in valid_intents:
        assert is_tavily_verification_intent(phrase), f"Failed to match intent: {phrase}"

    non_intents = [
        "What is the weather today?",
        "Help me write a Python script",
        "Add task: finish devpost demo",
        "Who is the CEO of Nebius?",
    ]
    for phrase in non_intents:
        assert not is_tavily_verification_intent(phrase), f"Wrongly matched intent: {phrase}"


def test_verification_target_resolution_from_history():
    """14. References to 'it' or 'this' resolve to previous assistant message."""
    history = [
        {"role": "user", "content": "When is the Nebius Buildathon due?"},
        {
            "role": "assistant",
            "content": "The Nebius Buildathon Phase 2 submission deadline is October 20, 2026 at 11:59 PM PDT.",
        },
    ]

    target = extract_verification_target("Verify it with Tavily", history)
    assert "Nebius Buildathon" in target or "submission deadline" in target

    target_this = extract_verification_target("Check this with Tavily", history)
    assert "Nebius Buildathon" in target_this

    # Direct claim query without pronouns
    direct_target = extract_verification_target("Verify with Tavily: Devpost submission is Oct 25", history)
    assert "Devpost submission is Oct 25" in direct_target


@pytest.mark.asyncio
async def test_tavily_handler_claim_level_verification():
    """15-18. Tavily verification pipeline executes and returns structured evidence and verdict."""
    mock_pipeline_res = {
        "verdict": "VERIFIED",
        "summary": "Official Devpost guidelines confirm submission ends October 25, 2026 at 5:00 PM EDT.",
        "evidence_ledger": [
            {
                "verdict": "VERIFIED",
                "authority_tier": "tier_1_official",
                "authority_badge": "Official Organizer",
                "source_url": "https://nebius-buildathon.devpost.com/rules",
                "display_quote": "Submissions close October 25, 2026 at 5:00 PM EDT.",
                "local_deadline_ist": "October 26, 2026, 02:30 IST",
            }
        ],
        "sources": [
            {
                "title": "Nebius Buildathon Official Rules",
                "url": "https://nebius-buildathon.devpost.com/rules",
                "authority_tier": "tier_1_official",
            }
        ],
    }

    with patch("backend.services.tavily_pipeline.run_tavily_research", new=AsyncMock(return_value=mock_pipeline_res)):
        res = await handle_verify_with_tavily(
            {"claim": "The submission deadline is October 25, 2026"},
            pool=None,
        )

    assert res["success"] is True
    assert res["data"]["verdict"] == "VERIFIED"
    assert "evidence" in res["data"]
    assert len(res["data"]["evidence"]["items"]) == 1
    assert "Verified on:" in res["response"]
    assert "Official Organizer" in res["response"]


@pytest.mark.asyncio
async def test_tavily_handler_unverified_fallback_on_error():
    """16. An authoritative failure reports COULD_NOT_CHECK (never a verdict, never the raw error)."""
    with patch("backend.services.tavily_pipeline.run_tavily_research", side_effect=Exception("API connection timeout")):
        res = await handle_verify_with_tavily(
            {"claim": "Contested deadline claim"},
            pool=None,
        )

    assert res["success"] is False
    assert res["data"]["verdict"] == "COULD_NOT_CHECK"
    assert "not available right now" in res["response"].lower() or "could not check" in res["response"].lower()
    assert "API connection timeout" not in res["response"]


# ============================================================================
# 3. DYNAMIC CURRENT-DATE AND TIMEZONE INTEGRITY
# ============================================================================

def test_dynamic_current_date_in_agent_system_prompt():
    """23-27. System prompt injects real server runtime clock and date consistency constraints."""
    prompt = _build_agent_system_prompt(["search_web", "add_task", "verify_with_tavily"])
    now_dt = datetime.now().astimezone()
    current_year_str = str(now_dt.year)
    current_month_str = now_dt.strftime("%B")

    # Dynamic clock validation
    assert "Dynamic Runtime Clock:" in prompt
    assert "Current trusted server date & time:" in prompt
    assert current_year_str in prompt
    assert current_month_str in prompt

    # Temporal integrity rules
    assert "Temporal & Event Consistency:" in prompt
    assert "An event whose end date or submission deadline is before today MUST be designated as [ENDED]" in prompt
    assert "Distinguish event dates from registration deadlines" in prompt


# ============================================================================
# 4. DEADLINE CLASSIFICATION & DEMO SEED INTEGRITY
# ============================================================================

@pytest.mark.asyncio
async def test_demo_seed_covers_all_categories_dynamically():
    """33-34. Demo seed generates dynamic relative dates across all requested categories."""
    from backend.routers.tasks_verification import seed_demo_persona_endpoint
    from backend.dependencies import Identity
    from backend.config import get_settings
    settings = get_settings()

    mock_request = MagicMock()
    mock_identity = Identity(
        id="test_judge_user",
        is_admin=False,
        is_guest=False,
        user_id="test_judge_user",
    )

    created_tasks = []

    async def mock_fetchrow(query, *args):
        if "SELECT EXISTS" in query:
            return False
        if "SELECT id FROM tasks WHERE title = $1" in query:
            return None
        return None

    async def mock_execute(query, *args):
        return "EXECUTE 1"

    async def mock_fetchval(query, *args):
        return 1

    async def mock_create_task(conn, **kwargs):
        created_tasks.append(kwargs)
        return {"id": len(created_tasks), **kwargs}

    async def mock_get_or_create_project(conn, name, domain):
        return {"id": 1, "name": name, "domain": domain}

    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetchval = AsyncMock(side_effect=mock_fetchval)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.tasks_verification._get_current_identity", return_value=mock_identity), \
         patch("backend.routers.tasks_verification.get_pool", return_value=mock_pool), \
         patch.object(settings, "ENABLE_DEMO_SEEDING", True), \
         patch("backend.memory.structured.create_task", side_effect=mock_create_task), \
         patch("backend.memory.structured.get_or_create_project", side_effect=mock_get_or_create_project), \
         patch("backend.memory.structured.update_task", new=AsyncMock()):

        resp = await seed_demo_persona_endpoint(mock_request)

    today = date.today()
    assert len(created_tasks) >= 20, f"Expected at least 20 seeded demo tasks, got {len(created_tasks)}"

    overdue_tasks = [t for t in created_tasks if t.get("due_date") and t["due_date"] < today and t.get("status") == "open"]
    due_today_tasks = [t for t in created_tasks if t.get("due_date") == today and t.get("status") == "open"]
    future_tasks = [t for t in created_tasks if t.get("due_date") and t["due_date"] > today and t.get("status") == "open"]
    backlog_tasks = [t for t in created_tasks if t.get("due_date") is None and t.get("status") == "open"]
    completed_tasks = [t for t in created_tasks if t.get("status") == "completed"]
    blocked_tasks = [t for t in created_tasks if t.get("status") == "blocked"]
    cancelled_tasks = [t for t in created_tasks if t.get("status") == "cancelled"]

    assert len(overdue_tasks) >= 2, f"Expected at least 2 overdue tasks, got {len(overdue_tasks)}"
    assert len(due_today_tasks) >= 2, f"Expected at least 2 tasks due today, got {len(due_today_tasks)}"
    assert len(future_tasks) >= 7, f"Expected at least 7 future upcoming tasks, got {len(future_tasks)}"
    assert len(backlog_tasks) >= 2, f"Expected at least 2 backlog tasks, got {len(backlog_tasks)}"
    assert len(completed_tasks) >= 2, f"Expected at least 2 completed tasks, got {len(completed_tasks)}"
    assert len(blocked_tasks) >= 1, f"Expected at least 1 blocked tasks, got {len(blocked_tasks)}"


# ============================================================================
# 5. ROUTER & STREAMING VERIFICATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_router_routes_verify_it_with_tavily_to_handler():
    """13-14. Router intercepts 'Verify it with Tavily' and routes to verify_with_tavily tool."""
    from backend.router import route_message

    history = [
        {"role": "user", "content": "When is the Nebius Buildathon Phase 2 due?"},
        {
            "role": "assistant",
            "content": "Nebius Buildathon Phase 2 is due October 25, 2026.",
        },
    ]

    skill_name, args, text_reply = await route_message(
        "Verify it with Tavily.",
        history=history,
    )

    assert skill_name == "verify_with_tavily"
    assert isinstance(args, dict)
    assert "claim" in args
    assert "Nebius Buildathon Phase 2 is due October 25, 2026" in args["claim"]


@pytest.mark.asyncio
async def test_chat_stream_passes_evidence_and_truncation_in_done_event():
    """28-32. Chat stream attaches evidence and is_truncated flags to the SSE done event."""
    import json
    from backend.services.chat_stream import generate_chat_events
    from backend.models import StreamChatRequest

    req = StreamChatRequest(
        message="Verify this with Tavily",
        conversation_id="11111111-1111-1111-1111-111111111111",
    )
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    fake_orchestrator_res = {
        "conversation_id": "11111111-1111-1111-1111-111111111111",
        "response": "Here is the verified report.",
        "skill_used": "verify_with_tavily",
        "data": {
            "evidence": {
                "verdict": "VERIFIED",
                "items": [{"source_url": "https://nebius.com", "verdict": "VERIFIED"}],
            },
            "is_truncated": False,
        },
    }

    with patch("backend.services.chat_stream.orchestrator.handle_message", new=AsyncMock(return_value=fake_orchestrator_res)), \
         patch("backend.services.chat_stream._schedule_stream_persistence", new=MagicMock()):

        events = []
        async for sse_item in generate_chat_events(req, mock_request):
            events.append(sse_item)

    done_event = [e for e in events if '"type": "done"' in e]
    assert len(done_event) == 1, "Expected exactly one done SSE event"

    line = done_event[0].replace("data: ", "").strip()
    payload = json.loads(line)

    assert payload["type"] == "done"
    assert payload["skill_used"] == "verify_with_tavily"
    assert "evidence" in payload
    assert payload["evidence"]["verdict"] == "VERIFIED"

