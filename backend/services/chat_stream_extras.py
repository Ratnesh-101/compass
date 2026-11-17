"""
Compass — chat stream building blocks (WS-B "chat never cut off").

Kept out of chat_stream.py so that file does not grow:
  * one streamed text pass with reasoning-aware status events and a think-tag filter,
  * the bounded "continue exactly where you left off" loop (all tones, same prompt),
  * continue mode for an already-saved assistant message,
  * early "committed" events from inside the orchestrator hand-off,
  * persisted truncation state, saved-candidate-profile context, and the web-search fallback.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from backend.services.chat_idempotency import (
    committed_event,
    reset_commit_listener,
    set_commit_listener,
)
from backend.services.streaming_filter import StreamingThinkFilter
from backend.services.token_budget import CONTINUE_PROMPT

logger = logging.getLogger("compass.services.chat_stream_extras")

# Streaming read timeout: the gap allowed between chunks. Routing uses a short client timeout, but a
# reasoning model can be silent for tens of seconds before its first token.
STREAM_REQUEST_TIMEOUT_S = 90.0

FRIENDLY_TIMEOUT_MESSAGE = "That took too long and the connection dropped. Your question is saved. Try again?"
GENERIC_ERROR_MESSAGE = "Something went wrong on our side. Your question is saved. Try again?"
FINISHING_LABEL = "Finishing the answer…"
DIRECT_ANSWER_RULE = "\n\nAnswer directly. Keep any internal deliberation very short so the full answer fits."
CONTINUE_FAILED_LABEL = "I couldn't finish the rest of the answer. You can ask me to continue."

STATUS_TRUNCATED = "truncated"
STATUS_INTERRUPTED = "interrupted"


def sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def status_event(stage: str, label: str) -> str:
    return sse({"type": "status", "stage": stage, "label": label})


def friendly_error_event(partial: str = "", detail: str = FRIENDLY_TIMEOUT_MESSAGE) -> str:
    payload: Dict[str, Any] = {"type": "error", "detail": detail, "can_retry": True, "terminal": True}
    if partial.strip():
        payload["partialResponse"] = partial.strip()
    return sse(payload)


@dataclass
class StreamState:
    """Mutable record of what has been streamed to the client so far."""

    full_text: str = ""
    emitted_text: str = ""
    finish: Optional[str] = None  # finish reason of the LAST completed pass
    thinking_sent: bool = False
    disconnected: bool = False
    continuation_failed: bool = False
    failed: bool = False  # the pass(es) raised or produced no visible text at all
    tool_call_detected: bool = False
    tool_calls: Dict[int, Dict[str, str]] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """True when the last pass that ran ended on the token limit (or its continuation failed)."""
        return self.finish == "length"


async def _aclose(stream: Any) -> None:
    closer = getattr(stream, "aclose", None)
    if closer is None:
        return
    try:
        res = closer()
        if inspect.isawaitable(res):
            await res
    except Exception:  # closing is best-effort
        pass


async def text_pass_events(
    client: Any,
    kwargs: Dict[str, Any],
    state: StreamState,
    request: Any,
    label: Optional[str] = None,
    allow_tools: bool = False,
) -> AsyncGenerator[str, None]:
    """Run ONE streamed completion, yielding SSE token/status events and updating `state`.

    With `allow_tools` the model's tool calls are collected into `state.tool_calls` (the caller then
    dispatches them) instead of being ignored.
    Raises if the completion cannot be created or the stream breaks; the caller decides what to tell the user."""
    call_kwargs = {**kwargs, "stream": True, "timeout": STREAM_REQUEST_TIMEOUT_S}
    stream = await client.chat.completions.create(**call_kwargs)
    state.finish = None
    think_filter = StreamingThinkFilter()

    def _take(text: str) -> List[str]:
        events: List[str] = []
        if label and not state.emitted_text:
            events.append(status_event("generating", label))
        state.full_text += text
        state.emitted_text += text
        events.append(sse({"type": "token", "value": text}))
        return events

    try:
        async for chunk in stream:
            if await request.is_disconnected():
                state.disconnected = True
                state.full_text += think_filter.flush()  # keep text still held back so the saved partial is complete
                return
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            finish_reason = choices[0].finish_reason
            if isinstance(finish_reason, str) and finish_reason:
                state.finish = finish_reason
            if allow_tools:
                tcs = getattr(delta, "tool_calls", None) if delta else None
                if tcs:
                    state.tool_call_detected = True
                    for tc in tcs:
                        slot = state.tool_calls.setdefault(getattr(tc, "index", 0) or 0, {"name": "", "arguments": ""})
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                slot["name"] += fn.name
                            if getattr(fn, "arguments", None):
                                slot["arguments"] += fn.arguments
                if finish_reason in ("tool_calls", "function_call") or (state.tool_call_detected and finish_reason):
                    state.tool_call_detected = True
                    break
            reasoning = (getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)) if delta else None
            if isinstance(reasoning, str) and reasoning and not state.thinking_sent and not state.emitted_text:
                state.thinking_sent = True
                yield status_event("thinking", "Thinking it through…")
            token = (delta.content if delta else None) or ""
            if token:
                visible = think_filter.process(token)
                if visible:
                    for evt in _take(visible):
                        yield evt
        tail = "" if state.tool_call_detected else think_filter.flush()
        if tail:
            for evt in _take(tail):
                yield evt
    finally:
        await _aclose(stream)


async def continuation_events(
    client: Any,
    base_kwargs: Dict[str, Any],
    messages: List[Dict[str, Any]],
    state: StreamState,
    request: Any,
    max_attempts: int,
    assistant_prefix: str = "",
) -> AsyncGenerator[str, None]:
    """Bounded continuation of an answer that ended on the token limit.

    Skipped when nothing visible was produced. Uses the same "continue exactly where you left off"
    prompt for every tone. A failing continuation call is reported with a status event."""
    attempts = 0
    while state.finish == "length" and state.full_text.strip() and attempts < max_attempts:
        if await request.is_disconnected():
            state.disconnected = True
            return
        attempts += 1
        logger.info("Chat stream hit the token limit; finishing the answer (%d/%d)", attempts, max_attempts)
        yield status_event("generating", FINISHING_LABEL)
        cont_messages = list(messages) + [
            {"role": "assistant", "content": assistant_prefix + state.full_text},
            {"role": "user", "content": CONTINUE_PROMPT},
        ]
        try:
            async for evt in text_pass_events(client, {**base_kwargs, "messages": cont_messages}, state, request):
                yield evt
        except Exception as err:
            logger.warning("Continuation attempt %d failed: %s", attempts, err)
            state.continuation_failed = True
            yield status_event("generating", CONTINUE_FAILED_LABEL)
            return
        if state.disconnected:
            return


# ---------------------------------------------------------------------------
# "committed" as soon as the row is written (T-007)
# ---------------------------------------------------------------------------

async def orchestrate_with_early_commit(
    handle_message: Callable[..., Any], **kwargs: Any
) -> AsyncGenerator[Tuple[str, Any], None]:
    """Run the orchestrator and yield ("committed", sse) the moment a mutation row is written,
    then ("result", result_dict). Falls back to the normal post-hoc event when no early signal fired."""
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    token = set_commit_listener(queue.put_nowait)
    try:
        task = asyncio.ensure_future(handle_message(**kwargs))
    finally:
        reset_commit_listener(token)

    emitted = False
    getter: Optional["asyncio.Future[Dict[str, Any]]"] = None
    try:
        while not task.done():
            if getter is None:
                getter = asyncio.ensure_future(queue.get())
            await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                evt = committed_event(getter.result())
                getter = None
                if evt and not emitted:
                    emitted = True
                    yield ("committed", evt)
        while not queue.empty() and not emitted:
            evt = committed_event(queue.get_nowait())
            if evt:
                emitted = True
                yield ("committed", evt)
    finally:
        if getter is not None and not getter.done():
            getter.cancel()
    result = task.result()
    if not emitted:
        evt = committed_event(result)
        if evt:
            yield ("committed", evt)
    yield ("result", result)


# ---------------------------------------------------------------------------
# Specialist answers stream through the same token loop (T-006)
# ---------------------------------------------------------------------------

SPECIALIST_FAILED_MESSAGE = "I couldn't write that answer this time. Your question is saved. Try again?"


async def specialist_answer_events(
    *,
    client: Any,
    settings: Any,
    request: Any,
    spec_result: Dict[str, Any],
    user_goal: str,
    state: StreamState,
    max_tokens: int,
    use_model: bool,
) -> AsyncGenerator[str, None]:
    """Stream the written specialist answer. On return `state.full_text` is the model text;
    `state.failed` is set when nothing usable could be written (the caller then sends an error event)."""
    from backend.agents.specialist import SPECIALIST_DIRECT_ANSWER_RULE, build_specialist_messages

    capability = spec_result.get("capability") or "specialist"
    header = spec_result.get("task_created_header") or ""
    fallback = spec_result.get("summary") or ""
    if header:
        yield sse({"type": "token", "value": header})

    if spec_result.get("status") not in (None, "success") or not use_model:
        state.full_text = fallback  # no model to ask (or the specialist itself is unavailable): plain summary
        if fallback:
            yield sse({"type": "token", "value": fallback})
        return

    messages = build_specialist_messages(capability, user_goal, spec_result.get("findings") or {})
    base_kwargs = {"model": settings.ROUTER_MODEL, "max_tokens": max_tokens, "temperature": 0.5}
    yield status_event("generating", f"Writing the {capability} answer…")
    pass_messages = messages
    for attempt in (0, 1):
        try:
            async for evt in text_pass_events(client, {**base_kwargs, "messages": pass_messages}, state, request):
                yield evt
        except Exception as err:
            logger.warning("Specialist %s stream failed: %s", capability, err)
            state.failed = True
            return
        if state.disconnected or state.full_text.strip():
            break
        if attempt == 0:
            # Nothing visible (reasoning used the budget): ask once more for a direct answer.
            yield status_event("thinking", "Still working on it…")
            pass_messages = [
                {**m, "content": m["content"] + SPECIALIST_DIRECT_ANSWER_RULE} if m.get("role") == "system" else dict(m)
                for m in messages
            ]
    if state.disconnected:
        return
    if not state.full_text.strip():
        state.failed = True
        return
    max_attempts = int(getattr(settings, "MAX_CONTINUATION_ATTEMPTS", 2))
    async for evt in continuation_events(client, base_kwargs, pass_messages, state, request, max_attempts):
        yield evt


# ---------------------------------------------------------------------------
# Persisted truncation / interruption state (T-011)
# ---------------------------------------------------------------------------

async def mark_message_state(conn: Any, message_id: Any, is_truncated: bool, status: Optional[str]) -> None:
    """Record on a stored assistant message that its text is cut short or interrupted. Never raises."""
    if message_id is None or not (is_truncated or status):
        return
    try:
        await conn.execute(
            "UPDATE messages SET is_truncated = $2, stream_status = $3 WHERE id = $1",
            message_id, bool(is_truncated), status,
        )
    except Exception as e:  # column missing on an old database, or a fake connection in tests
        logger.debug("Could not store message truncation state: %s", e)


async def fetch_message_states(conn: Any, message_ids: List[Any]) -> Dict[Any, Tuple[bool, Optional[str]]]:
    """{message_id: (is_truncated, stream_status)} for the given ids. Empty on any failure."""
    if not message_ids:
        return {}
    try:
        rows = await conn.fetch(
            "SELECT id, is_truncated, stream_status FROM messages WHERE id = ANY($1)", message_ids
        )
        return {r["id"]: (bool(r["is_truncated"]), r["stream_status"]) for r in rows}
    except Exception as e:
        logger.debug("Could not read message truncation state: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Continue mode (T-004)
# ---------------------------------------------------------------------------

async def load_continue_target(pool: Any, message_id_raw: Any, owner_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The caller's own assistant message to continue plus the few messages before it, or None."""
    if not (pool and owner_id and str(message_id_raw or "").isdigit()):
        return None
    mid = int(str(message_id_raw))
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT m.id, m.role, m.content, m.conversation_id FROM messages m "
                "JOIN conversations c ON m.conversation_id = c.id "
                "WHERE m.id = $1 AND (c.user_id = $2 OR c.guest_id = $2)",
                mid, owner_id,
            )
            if not row or row["role"] != "assistant" or not row["content"]:
                return None
            prior = await conn.fetch(
                "SELECT role, content FROM messages WHERE conversation_id = $1 AND id < $2 ORDER BY id DESC LIMIT 6",
                row["conversation_id"], row["id"],
            )
    except Exception as e:
        logger.warning("Could not load message %s to continue: %s", message_id_raw, e)
        return None
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in reversed(list(prior)) if r["role"] in ("user", "assistant") and r["content"]
    ]
    return {
        "id": row["id"], "content": row["content"], "conversation_id": str(row["conversation_id"]),
        "history": history,
    }


async def _append_to_message(pool: Any, message_id: Any, new_text: str, truncated: bool, status: Optional[str]) -> None:
    if not (pool and new_text):
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE messages SET content = content || $2 WHERE id = $1", message_id, new_text)
            await mark_message_state(conn, message_id, truncated, status)
            if not truncated and not status:
                try:
                    await conn.execute(
                        "UPDATE messages SET is_truncated = FALSE, stream_status = NULL WHERE id = $1", message_id
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error("Could not append continued text to message %s: %s", message_id, e)


async def continue_message_events(
    *,
    client: Any,
    settings: Any,
    request: Any,
    pool: Any,
    owner_id: Optional[str],
    message_id_raw: Any,
    system_prompt: str,
    max_tokens: int,
) -> AsyncGenerator[str, None]:
    """Resume a saved assistant message: stream only the NEW text and append it to that message."""
    target = await load_continue_target(pool, message_id_raw, owner_id)
    if not target:
        yield sse({
            "type": "error", "detail": "I couldn't find that answer to continue. Please ask again.",
            "can_retry": False, "terminal": True,
        })
        return

    state = StreamState()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *target["history"],
        {"role": "assistant", "content": target["content"]},
        {"role": "user", "content": CONTINUE_PROMPT},
    ]
    base_kwargs = {"model": settings.ROUTER_MODEL, "max_tokens": max_tokens, "temperature": 0.7}
    yield status_event("generating", FINISHING_LABEL)
    try:
        async for evt in text_pass_events(client, {**base_kwargs, "messages": messages}, state, request):
            yield evt
        if not state.disconnected:
            max_attempts = int(getattr(settings, "MAX_CONTINUATION_ATTEMPTS", 2))
            async for evt in continuation_events(
                client, base_kwargs, messages[:-2], state, request, max_attempts, assistant_prefix=target["content"]
            ):
                yield evt
    except Exception as err:
        logger.error("Continue mode failed for message %s: %s", target["id"], err, exc_info=True)
        await _append_to_message(pool, target["id"], state.full_text, True, STATUS_INTERRUPTED)
        yield friendly_error_event(partial=state.full_text)
        return

    if state.disconnected:
        await _append_to_message(pool, target["id"], state.full_text, True, STATUS_INTERRUPTED)
        return
    await _append_to_message(
        pool, target["id"], state.full_text, state.truncated, STATUS_TRUNCATED if state.truncated else None
    )
    yield sse({
        "type": "done", "conversation_id": target["conversation_id"], "skill_used": "chat",
        "is_truncated": state.truncated, "continued_message_id": target["id"],
    })


# ---------------------------------------------------------------------------
# Saved Career profile in chat context (N-010)
# ---------------------------------------------------------------------------

def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def format_candidate_profile(profile: Any, full_name: str = "") -> str:
    """One compact context block from the saved candidate profile, or '' when there is nothing to say."""
    parts: List[str] = []
    if full_name:
        parts.append(f"Name: {full_name}")
    degree = " ".join(x for x in (getattr(profile, "degree", None), getattr(profile, "degree_specialization", None)) if x)
    if degree:
        parts.append(f"Degree: {degree}")
    if getattr(profile, "university", None):
        parts.append(f"University: {profile.university}")
    year = getattr(profile, "academic_year", None)
    if isinstance(year, int):
        parts.append(f"Current year of study: {_ordinal(year)} year")
    if getattr(profile, "grad_year", None):
        parts.append(f"Graduation year: {profile.grad_year}")
    cgpa = getattr(profile, "cgpa", None)
    if cgpa is not None:
        scale = getattr(profile, "cgpa_scale", None) or 10.0
        parts.append(f"CGPA: {cgpa}/{scale:g}")
    skills = [s for s in (getattr(profile, "skills", None) or []) if s][:15]
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    country = getattr(profile, "country_of_study", None)
    if country:
        parts.append(f"Country: {country}")
    if not parts:
        return ""
    return (
        "[CANDIDATE PROFILE saved in the Career tab. Use these facts directly; do not ask the user for them "
        "and never write placeholders like [Your Name]]:\n" + "\n".join(f"- {p}" for p in parts)
    )


async def load_candidate_profile_context(owner_id: Optional[str]) -> str:
    """Read-only: the caller's saved candidate profile as a context block. '' on any miss or error."""
    if not owner_id:
        return ""
    try:
        from backend.memory.radar import get_user_opportunity_profile

        profile = await get_user_opportunity_profile(owner_id)
        full_name = ""
        try:
            from backend.memory.career import get_master_resume

            master = await get_master_resume(owner_id)
            full_name = (getattr(getattr(master, "content", None), "full_name", "") or "").strip()
        except Exception:
            full_name = ""
        if profile is None and not full_name:
            return ""
        if profile is None:
            return f"[CANDIDATE PROFILE saved in the Career tab]:\n- Name: {full_name}"
        return format_candidate_profile(profile, full_name)
    except Exception as e:
        logger.debug("Candidate profile context unavailable: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Web-search fallback for external-fact questions (T-013)
# ---------------------------------------------------------------------------

_DEADLINE_RE = re.compile(
    r"\b(deadline|due date|submission (?:date|deadline|period|window)|closes?|closing|registration (?:deadline|closes))\b",
    re.IGNORECASE,
)
_EVENT_RE = re.compile(
    r"\b(hackathon|buildathon|devpost|competition|contest|challenge|conference|summit|grant|fellowship|scholarship)\b",
    re.IGNORECASE,
)
_PERSONAL_RE = re.compile(r"\b(my|mine|our|i have|do i|am i|i've|i need to)\b", re.IGNORECASE)
_OFFICIAL_RE = re.compile(r"\b(official|actual|public)\b", re.IGNORECASE)
_ABSTAIN_RE = re.compile(
    r"(don't|do not|doesn't|does not|didn't)\s+(?:currently\s+)?(?:have|know|see|find)|couldn't find|could not find|"
    r"unable to find|no (?:recorded|stored|saved|matching|active)|not (?:recorded|stored|saved)|"
    r"found 0\b|i'm not sure|i am not sure|not aware of",
    re.IGNORECASE,
)

MEMORY_LOOKUP_SKILLS = frozenset({
    "get_hackathon_deadlines", "query_code_context", "query_tasks", "query_coursework_tasks",
    "query_coursework_notes", "query_projects", "list_projects",
})
WEB_SKILLS = frozenset({"search_web", "deep_research", "verify_with_tavily", "verify_deadline", "ingest_url"})


def is_external_fact_question(message: str) -> bool:
    """A question about an outside event's deadline (not the user's own task list)."""
    text = message or ""
    if not (_DEADLINE_RE.search(text) and _EVENT_RE.search(text)):
        return False
    if _PERSONAL_RE.search(text) and not _OFFICIAL_RE.search(text):
        return False
    return True


def memory_lookup_was_empty(result: Dict[str, Any]) -> bool:
    if (result.get("skill_used") or "") not in MEMORY_LOOKUP_SKILLS:
        return False
    data = result.get("data")
    if isinstance(data, dict):
        if data.get("count") == 0:
            return True
        return any(k in data and not data[k] for k in ("tasks", "chunks", "results"))
    if isinstance(data, list):
        return not data
    return bool(_ABSTAIN_RE.search(str(result.get("response") or "")))


def should_search_web(message: str, result: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> bool:
    """True when an external-fact question got an empty memory lookup or an "I don't know" reply."""
    if not is_external_fact_question(message):
        return False
    if result is not None and (result.get("skill_used") or "") in WEB_SKILLS:
        return False  # already went to the web
    reply = text if text is not None else (result or {}).get("response")
    if result is not None and memory_lookup_was_empty(result):
        return True
    return bool(reply and _ABSTAIN_RE.search(str(reply)))


async def run_web_fallback(message: str, pool: Any) -> Optional[Dict[str, Any]]:
    """Run search_web for the question. None when Tavily is off, over budget, or returns nothing, so the
    caller then falls through unchanged. Budgets are enforced inside the Tavily service itself."""
    from backend.services import budget_context, tavily as tavily_service

    if not tavily_service.tavily_available():
        return None
    counter_token = budget_context.ensure_run_counter()
    try:
        from backend.skills.handlers.web import handle_search_web

        res = await handle_search_web({"query": message.strip()[:380]}, pool)
    except Exception as e:
        logger.info("Web fallback skipped: %s", e)
        return None
    finally:
        if counter_token is not None:
            budget_context.end_run_counter(counter_token)
    if not isinstance(res, dict) or not res.get("success") or not str(res.get("response") or "").strip():
        return None
    return res
