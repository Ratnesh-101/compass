"""Regression tests for WS-B "chat never cut off" (backend half).

Covers T-003, T-004 (server side), T-006, T-007 (server side), T-008, T-009, T-010, T-011 (server side),
T-013, N-009, N-010 and N-011 (server side). Everything uses fake streaming models and fake pools; no
network or database is needed.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.config import get_settings
from backend.models import StreamChatRequest
from backend.routers.chat import StreamChatRequestV2
from backend.services.chat_stream import generate_chat_events, persist_stream_messages
from backend.services.chat_stream_extras import (
    CONTINUE_FAILED_LABEL,
    FINISHING_LABEL,
    FRIENDLY_TIMEOUT_MESSAGE,
    fetch_message_states,
    format_candidate_profile,
    is_external_fact_question,
    mark_message_state,
    orchestrate_with_early_commit,
    should_search_web,
)
from backend.services.streaming_filter import StreamingThinkFilter
from backend.services.token_budget import CONTINUE_PROMPT, stream_token_budget


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Delta:
    def __init__(self, content="", reasoning=None, tool_calls=None):
        self.content = content
        self.reasoning = reasoning
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices):
        self.choices = choices
        self.usage = None


class _Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self.chunks:
            yield c

    async def aclose(self):
        pass


def _text_stream(text, finish="stop"):
    return _Stream([_Chunk([_Choice(_Delta(text), None)]), _Chunk([_Choice(_Delta(""), finish)])])


def _reasoning_only_stream(finish="length"):
    return _Stream([
        _Chunk([_Choice(_Delta("", reasoning="pondering the question"), None)]),
        _Chunk([_Choice(_Delta(""), finish)]),
    ])


def _request():
    r = MagicMock()
    r.is_disconnected = AsyncMock(return_value=False)
    return r


def _parse(events):
    out = []
    for line in events:
        for part in line.splitlines():
            part = part.strip()
            if part.startswith("data: "):
                try:
                    out.append(json.loads(part[6:]))
                except json.JSONDecodeError:
                    pass
    return out


async def _drive(req, side_effect, *, pool=None, user_id=None, settings=None, extra_patches=()):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    patches = [
        patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=client),
        patch("backend.router.get_openai_client", return_value=client),
        patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=pool)),
        patch("backend.services.chat_stream.record_usage", MagicMock()),
        patch("backend.services.chat_stream._schedule_stream_persistence", MagicMock()),
    ]
    if settings is not None:
        patches.append(patch("backend.services.chat_stream.get_settings", return_value=settings))
    patches.extend(extra_patches)
    for p in patches:
        p.start()
    try:
        raw = [line async for line in generate_chat_events(req, _request(), user_id=user_id)]
    finally:
        for p in reversed(patches):
            p.stop()
    return _parse(raw), client.chat.completions.create.call_args_list


def _live_settings():
    base = get_settings()
    return SimpleNamespace(
        NEBIUS_API_KEY="real-looking-key", NEBIUS_BASE_URL="http://example.invalid/v1",
        ROUTER_MODEL=base.ROUTER_MODEL, MAX_SYNTHESIS_TOKENS=8192, MAX_CONTINUATION_ATTEMPTS=2,
    )


# ---------------------------------------------------------------------------
# T-003: tone is style only, every tone gets the full budget and the same continue prompt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tone", ["brief", "balanced", "detailed", "exploratory", None])
def test_every_tone_gets_full_budget(tone):
    assert stream_token_budget(tone, 8192) == (8192, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("tone", ["brief", "balanced"])
async def test_continuation_uses_continue_prompt_and_no_counter_text(tone):
    msg = "Explain how a hash map works in detail"
    events, calls = await _drive(
        StreamChatRequest(message=msg, tone=tone),
        [_text_stream("A hash map stores keys", "length"), _text_stream(" in buckets.", "stop")],
    )
    assert len(calls) == 2
    assert calls[1].kwargs["max_tokens"] == int(get_settings().MAX_SYNTHESIS_TOKENS)
    assert calls[1].kwargs["messages"][-1]["content"] == CONTINUE_PROMPT
    labels = [e.get("label", "") for e in events if e.get("type") == "status"]
    assert FINISHING_LABEL in labels
    assert not any("(1/" in lab or "Continuing response" in lab for lab in labels)
    done = [e for e in events if e["type"] == "done"][0]
    assert not done.get("is_truncated")


@pytest.mark.asyncio
async def test_failed_continuation_sends_status_event_and_keeps_truncated_flag():
    events, calls = await _drive(
        StreamChatRequest(message="Explain how a hash map works", tone="balanced"),
        [_text_stream("A hash map stores keys", "length"), RuntimeError("boom")],
    )
    labels = [e.get("label") for e in events if e.get("type") == "status"]
    assert CONTINUE_FAILED_LABEL in labels
    done = [e for e in events if e["type"] == "done"][0]
    assert done.get("is_truncated") is True


# ---------------------------------------------------------------------------
# T-008: empty first pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_first_pass_retries_model_once_and_never_uses_orchestrator():
    handle = AsyncMock()
    events, calls = await _drive(
        StreamChatRequest(message="Explain recursion simply", tone="balanced"),
        [_reasoning_only_stream("length"), _text_stream("Recursion is a function calling itself.", "stop")],
        extra_patches=[patch("backend.services.chat_stream.orchestrator.handle_message", handle)],
    )
    handle.assert_not_awaited()
    assert len(calls) == 2  # first pass + one retry, no "continue" call for the empty pass
    assert all(c.kwargs["messages"][-1]["content"] != CONTINUE_PROMPT for c in calls)
    tokens = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert tokens == "Recursion is a function calling itself."
    thinking = [e for e in events if e.get("type") == "status" and e.get("stage") == "thinking"]
    assert thinking, "reasoning-only deltas must produce a thinking status"


@pytest.mark.asyncio
async def test_two_empty_passes_send_retryable_error():
    handle = AsyncMock()
    events, calls = await _drive(
        StreamChatRequest(message="Explain recursion simply", tone="balanced"),
        [_reasoning_only_stream("length"), _reasoning_only_stream("length")],
        extra_patches=[patch("backend.services.chat_stream.orchestrator.handle_message", handle)],
    )
    handle.assert_not_awaited()
    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["can_retry"] is True
    assert not [e for e in events if e["type"] == "done"]


# ---------------------------------------------------------------------------
# T-009: think filter
# ---------------------------------------------------------------------------

def _filter(chunks):
    f = StreamingThinkFilter()
    return "".join(f.process(c) for c in chunks) + f.flush()


def test_think_tag_mid_answer_is_kept():
    assert _filter(["Use the <think> tag like this. ", "Here is the rest…"]) == "Use the <think> tag like this. Here is the rest…"


def test_plain_text_streams_immediately():
    f = StreamingThinkFilter()
    assert f.process("Sure, ") == "Sure, "
    assert f.flush() == ""


def test_opening_tag_split_across_chunks_is_dropped():
    f = StreamingThinkFilter()
    assert f.process("<thi") == ""
    assert f.process("nk>hidden</think>Visible") == "Visible"


def test_message_opening_think_block_is_dropped():
    assert _filter(["  <think>hidden ", "thoughts</think>", "Shown."]) == "Shown."


def test_unclosed_opening_think_block_stays_private():
    assert _filter(["<think>never closed"]) == ""


def test_whitespace_then_partial_tag_prefix_is_held_and_flushed():
    f = StreamingThinkFilter()
    assert f.process("  <th") == ""
    assert f.flush() == "  <th"
    assert f.flush() == ""


def test_long_answer_streams_without_delay():
    f = StreamingThinkFilter()
    assert f.process("x" * 300) == "x" * 300
    assert f.process("more") == "more"


# ---------------------------------------------------------------------------
# T-004: continue mode
# ---------------------------------------------------------------------------

class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _Conn:
    def __init__(self, target=True):
        self.conv = uuid.uuid4()
        self.target = target
        self.executed = []

    async def fetchrow(self, sql, *args):
        if not self.target:
            return None
        return {"id": 7, "role": "assistant", "content": "Part one of the answer", "conversation_id": self.conv}

    async def fetch(self, sql, *args):
        return [{"role": "user", "content": "the question"}]

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_continue_mode_streams_only_new_text_and_appends_to_message():
    conn = _Conn()
    req = StreamChatRequestV2(message="Continue response", continue_message_id="7", tone="balanced")
    events, calls = await _drive(req, [_text_stream(" and part two.", "stop")], pool=_Pool(conn), user_id="u1")
    assert len(calls) == 1
    msgs = calls[0].kwargs["messages"]
    assert msgs[-1] == {"role": "user", "content": CONTINUE_PROMPT}
    assert msgs[-2] == {"role": "assistant", "content": "Part one of the answer"}
    tokens = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert tokens == " and part two."
    done = [e for e in events if e["type"] == "done"][0]
    assert done["continued_message_id"] == 7 and done["is_truncated"] is False
    updates = [x for x in conn.executed if "content = content ||" in x[0]]
    assert updates and updates[0][1] == (7, " and part two.", "Part one of the answer")


@pytest.mark.asyncio
async def test_continue_mode_keeps_truncated_flag_when_cut_again():
    conn = _Conn()
    req = StreamChatRequestV2(message="Continue response", continue_message_id=7)
    events, _ = await _drive(
        req, [_text_stream(" more", "length"), RuntimeError("down")], pool=_Pool(conn), user_id="u1"
    )
    done = [e for e in events if e["type"] == "done"][0]
    assert done["is_truncated"] is True


@pytest.mark.asyncio
async def test_continue_mode_rejects_foreign_or_missing_message():
    conn = _Conn(target=False)
    req = StreamChatRequestV2(message="Continue response", continue_message_id="999")
    events, calls = await _drive(req, [_text_stream("x")], pool=_Pool(conn), user_id="u1")
    assert not calls
    assert [e for e in events if e["type"] == "error"][0]["can_retry"] is False


# ---------------------------------------------------------------------------
# T-006: specialist path streams
# ---------------------------------------------------------------------------

def _spec_result(**kw):
    base = {"capability": "coursework", "status": "success", "summary": "fallback text",
            "findings": {"tasks": [1]}, "task_created_header": ""}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_specialist_streams_with_statuses_full_budget_and_is_truncated_key():
    req = StreamChatRequest(message="Compare five vector databases in depth", specialist_id="coursework")
    run = AsyncMock(return_value=_spec_result())
    events, calls = await _drive(
        req, [_text_stream("The answer.", "stop")], settings=_live_settings(),
        extra_patches=[patch("backend.agents.specialist.run_specialist_task", run)],
    )
    assert run.await_args.kwargs["defer_synthesis"] is True
    assert calls[0].kwargs["max_tokens"] == 8192
    labels = [e.get("label", "") for e in events if e.get("type") == "status"]
    assert any(lab.startswith("Gathering") for lab in labels)
    assert any(lab.startswith("Writing") for lab in labels)
    assert "".join(e.get("value", "") for e in events if e["type"] == "token") == "The answer."
    done = [e for e in events if e["type"] == "done"][0]
    assert done["is_truncated"] is False and done["skill_used"] == "specialist_coursework"


@pytest.mark.asyncio
async def test_specialist_continues_a_cut_answer_and_reports_truncation_when_still_cut():
    req = StreamChatRequest(message="Compare five vector databases in depth", specialist_id="coursework")
    run = AsyncMock(return_value=_spec_result())
    streams = [_text_stream("One", "length"), _text_stream(" two", "length"), _text_stream(" three", "length")]
    events, calls = await _drive(
        req, streams, settings=_live_settings(),
        extra_patches=[patch("backend.agents.specialist.run_specialist_task", run)],
    )
    assert len(calls) == 3
    assert [e for e in events if e["type"] == "done"][0]["is_truncated"] is True


@pytest.mark.asyncio
async def test_specialist_with_no_text_sends_retryable_error_not_a_fallback_note():
    req = StreamChatRequest(message="Compare five vector databases in depth", specialist_id="coursework")
    run = AsyncMock(return_value=_spec_result())
    events, _ = await _drive(
        req, [_reasoning_only_stream("stop"), _reasoning_only_stream("stop")], settings=_live_settings(),
        extra_patches=[patch("backend.agents.specialist.run_specialist_task", run)],
    )
    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["can_retry"] is True
    assert not [e for e in events if e["type"] == "done"]
    assert "model returned no text" not in json.dumps(events)


# ---------------------------------------------------------------------------
# T-007: early committed event, request id validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_committed_event_is_sent_before_the_orchestrator_returns():
    from backend.services.chat_idempotency import record_committed_outcome

    gate = asyncio.Event()

    async def fake_handle(**kwargs):
        record_committed_outcome({"id": 5, "title": "T"}, conv_id="c")
        await gate.wait()
        return {"success": True, "skill_used": "add_task", "response": "ok", "data": {}}

    agen = orchestrate_with_early_commit(fake_handle, message="x")
    kind, evt = await asyncio.wait_for(agen.__anext__(), timeout=2)
    assert kind == "committed"
    assert json.loads(evt[6:])["type"] == "committed"
    gate.set()
    rest = [item async for item in agen]
    assert [k for k, _ in rest] == ["result"]  # not emitted a second time


def test_malformed_request_id_is_rejected_with_422():
    from backend.services.chat_idempotency import validate_request_id

    with pytest.raises(HTTPException) as exc:
        validate_request_id("abc")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        validate_request_id("has spaces in it!")
    assert validate_request_id("req_12345678") == "req_12345678"
    assert validate_request_id(None) is None
    assert validate_request_id("   ") is None


# ---------------------------------------------------------------------------
# T-010: keepalive and synthesis timeout
# ---------------------------------------------------------------------------

def test_agent_streams_are_wrapped_in_keepalive():
    import inspect

    import backend.routers.agent as agent_router

    src = inspect.getsource(agent_router)
    assert "with_keepalive(agent_event_generator())" in src
    assert "with_keepalive(event_generator())" in src


@pytest.mark.asyncio
async def test_agent_synthesis_has_full_budget_for_every_tone_and_a_long_timeout():
    from backend.agent_synthesis import force_final_synthesis, synthesis_timeout_seconds

    settings = get_settings()
    choice = MagicMock()
    choice.message.content = "Final answer."
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    await force_final_synthesis(
        client=client, settings=settings, messages=[{"role": "user", "content": "q"}], step_num=1,
        start_time=0.0, run_id="r", active_replan_diff=None, tone="brief",
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == settings.MAX_SYNTHESIS_TOKENS
    assert kwargs["timeout"] == synthesis_timeout_seconds(settings.MAX_SYNTHESIS_TOKENS) >= 60.0


# ---------------------------------------------------------------------------
# T-011: persisted truncation state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_message_state_writes_flag_and_status():
    conn = _Conn()
    await mark_message_state(conn, 11, True, "truncated")
    assert conn.executed[0][1] == (11, True, "truncated")
    await mark_message_state(conn, 12, False, None)  # nothing to record
    assert len(conn.executed) == 1


@pytest.mark.asyncio
async def test_fetch_message_states_maps_rows_and_survives_errors():
    class _C:
        async def fetch(self, sql, ids):
            return [{"id": 1, "is_truncated": True, "stream_status": "interrupted"}]

    assert await fetch_message_states(_C(), [1, 2]) == {1: (True, "interrupted")}

    class _Bad:
        async def fetch(self, sql, ids):
            raise RuntimeError("no such column")

    assert await fetch_message_states(_Bad(), [1]) == {}


@pytest.mark.asyncio
async def test_persist_stream_messages_stores_truncation_on_the_assistant_message():
    conn = _Conn()
    pool = _Pool(conn)
    add_message = AsyncMock(side_effect=[{"id": 10}, {"id": 11}])
    with patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=pool)), \
         patch("backend.services.chat_stream.conversations.get_or_create_conversation", AsyncMock(return_value=str(uuid.uuid4()))), \
         patch("backend.services.chat_stream.conversations.add_message", add_message):
        ok = await persist_stream_messages(
            str(uuid.uuid4()), "q", "half an answer", user_id="u", is_truncated=True, stream_status="truncated"
        )
    assert ok is True
    assert conn.executed[0][1] == (11, True, "truncated")


# ---------------------------------------------------------------------------
# T-013: web search for external-fact questions
# ---------------------------------------------------------------------------

README_PROMPT = "What is the official submission deadline for the Nebius x NVIDIA AI Hackathon?"
EMPTY_LOOKUP = {
    "skill_used": "get_hackathon_deadlines", "data": {"tasks": [], "count": 0},
    "response": "Found 0 active hackathon deliverable(s).",
}


def test_external_fact_detection():
    assert is_external_fact_question(README_PROMPT)
    assert not is_external_fact_question("What are my hackathon deadlines this week?")
    assert not is_external_fact_question("What is the capital of France?")
    assert should_search_web(README_PROMPT, EMPTY_LOOKUP)
    assert not should_search_web(README_PROMPT, {**EMPTY_LOOKUP, "skill_used": "search_web"})
    assert should_search_web(README_PROMPT, text="I don't have a recorded deadline for that.")
    assert not should_search_web(README_PROMPT, text="The deadline is Oct 30.")


class _TC:
    def __init__(self, index, name=None, args=None):
        self.index = index
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = args


def _tool_stream(name):
    return _Stream([
        _Chunk([_Choice(_Delta("", tool_calls=[_TC(0, name=name, args="{}")]), None)]),
        _Chunk([_Choice(_Delta(""), "tool_calls")]),
    ])


@pytest.mark.asyncio
async def test_zero_result_memory_tool_triggers_web_search_before_replying():
    handle = AsyncMock(return_value={**EMPTY_LOOKUP, "conversation_id": "c1"})
    web = AsyncMock(return_value={"response": "Official deadline: Oct 30, 2026.", "data": {"results": []}})
    events, _ = await _drive(
        StreamChatRequest(message=README_PROMPT, tone="balanced"),
        [_tool_stream("get_hackathon_deadlines")],
        extra_patches=[
            patch("backend.services.chat_stream.orchestrator.handle_message", handle),
            patch("backend.services.chat_stream.run_web_fallback", web),
            patch("backend.services.chat_stream.is_schedule_or_agent_intent", return_value=False),
        ],
    )
    web.assert_awaited_once()
    text = "".join(e.get("value", "") for e in events if e["type"] in ("token", "replace"))
    assert "Oct 30, 2026" in text
    assert [e for e in events if e["type"] == "done"][0]["skill_used"] == "search_web"


@pytest.mark.asyncio
async def test_failed_web_search_falls_through_unchanged():
    handle = AsyncMock(return_value={**EMPTY_LOOKUP, "conversation_id": "c1"})
    web = AsyncMock(return_value=None)  # Tavily off or over budget
    events, _ = await _drive(
        StreamChatRequest(message=README_PROMPT, tone="balanced"),
        [_tool_stream("get_hackathon_deadlines")],
        extra_patches=[
            patch("backend.services.chat_stream.orchestrator.handle_message", handle),
            patch("backend.services.chat_stream.run_web_fallback", web),
            patch("backend.services.chat_stream.is_schedule_or_agent_intent", return_value=False),
        ],
    )
    text = "".join(e.get("value", "") for e in events if e["type"] in ("token", "replace"))
    assert "Found 0 active hackathon" in text


@pytest.mark.asyncio
async def test_run_web_fallback_respects_tavily_disabled():
    from backend.services.chat_stream_extras import run_web_fallback

    with patch("backend.services.tavily.tavily_available", return_value=False):
        assert await run_web_fallback(README_PROMPT, None) is None


# ---------------------------------------------------------------------------
# N-009: web answers
# ---------------------------------------------------------------------------

def test_social_results_are_dropped():
    from backend.services.web_answer import drop_social_results, is_social_url

    assert is_social_url("https://www.instagram.com/p/abc")
    assert is_social_url("https://x.com/someone/status/1")
    assert is_social_url("https://mobile.twitter.com/a")
    assert not is_social_url("https://notx.com/page")
    kept = drop_social_results([
        {"url": "https://www.facebook.com/e", "content": "a"},
        {"url": "https://devpost.com/rules", "content": "b"},
        {"url": "https://www.tiktok.com/@x", "content": "c"},
    ])
    assert [r["url"] for r in kept] == ["https://devpost.com/rules"]


@pytest.mark.asyncio
async def test_web_answer_is_short_with_source_links_and_no_ellipsis():
    from backend.services.web_answer import synthesize_web_answer

    results = [{
        "title": "Rules", "url": "https://devpost.com/rules",
        "content": "The hackathon runs for six weeks. Teams of up to four people may enter this year. "
                   "Projects are judged on impact and a long tail of other things that goes on and on...",
    }]
    with patch("backend.config.get_settings", return_value=SimpleNamespace(NEBIUS_API_KEY="mock")):
        out = await synthesize_web_answer("hackathon rules", results)
    assert "**Sources:** [Rules](https://devpost.com/rules)" in out
    assert "..." not in out and "…" not in out
    assert len(out.split("\n\n")[0].split(". ")) <= 3


@pytest.mark.asyncio
async def test_search_web_handler_drops_social_and_returns_short_answer():
    from backend.skills.handlers.web import handle_search_web

    tavily_resp = {"results": [
        {"title": "Post", "url": "https://www.instagram.com/p/1", "content": "buy now", "score": 0.9},
        {"title": "Guide", "url": "https://example.edu/guide", "content": "Compass helps students plan work. It tracks deadlines.", "score": 0.5},
    ]}
    with patch("backend.services.tavily.tavily_available", return_value=True), \
         patch("backend.services.tavily.search", AsyncMock(return_value=tavily_resp)), \
         patch("backend.config.get_settings", return_value=SimpleNamespace(NEBIUS_API_KEY="mock")):
        res = await handle_search_web({"query": "what does compass do"}, None)
    urls = [r["url"] for r in res["data"]["results"]]
    assert urls == ["https://example.edu/guide"]
    assert "instagram" not in res["response"]
    assert "**Sources:**" in res["response"]


# ---------------------------------------------------------------------------
# N-010: saved candidate profile in chat context
# ---------------------------------------------------------------------------

def _profile():
    return SimpleNamespace(
        degree="B.Tech", degree_specialization="Computer Science", university="PICT", academic_year=3,
        grad_year=2027, cgpa=8.4, cgpa_scale=10.0, skills=["Python", "SQL"], country_of_study="India",
    )


def test_candidate_profile_block_has_the_facts():
    block = format_candidate_profile(_profile(), "Priya Sharma")
    for expected in ("Priya Sharma", "B.Tech Computer Science", "3rd year", "2027", "Python, SQL", "8.4/10"):
        assert expected in block
    assert "do not ask the user" in block


@pytest.mark.asyncio
async def test_load_candidate_profile_context_is_read_only_and_scoped_to_the_caller():
    from backend.services.chat_stream_extras import load_candidate_profile_context

    get_profile = AsyncMock(return_value=_profile())
    get_master = AsyncMock(return_value=SimpleNamespace(content=SimpleNamespace(full_name="Priya Sharma")))
    with patch("backend.memory.radar.get_user_opportunity_profile", get_profile), \
         patch("backend.memory.career.get_master_resume", get_master):
        ctx = await load_candidate_profile_context("guest-1")
    get_profile.assert_awaited_once_with("guest-1")
    get_master.assert_awaited_once_with("guest-1")
    assert "Priya Sharma" in ctx
    assert await load_candidate_profile_context(None) == ""


# ---------------------------------------------------------------------------
# N-011: plain wording
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mid_stream_failure_sends_friendly_retryable_error():
    class _Broken:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield _Chunk([_Choice(_Delta("Partial answer"), None)])
            raise ConnectionError("reset")

        async def aclose(self):
            pass

    events, _ = await _drive(StreamChatRequest(message="Explain recursion simply"), [_Broken()])
    err = [e for e in events if e["type"] == "error"][0]
    assert err["detail"] == FRIENDLY_TIMEOUT_MESSAGE
    assert err["can_retry"] is True
