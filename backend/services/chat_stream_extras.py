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
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from backend.services import stream_watch
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
    prompt_tokens: int = 0  # provider-reported usage summed over the passes run on this state
    completion_tokens: int = 0

    @property
    def truncated(self) -> bool:
        """True when the last pass that ran ended on the token limit (or its continuation failed)."""
        return self.finish == "length" or self.continuation_failed


def no_retry_client(client: Any) -> Any:
    """A real OpenAI client with SDK retries off, so STREAM_REQUEST_TIMEOUT_S bounds the wait (not 3x).
    Anything else (test fakes, mocks) is returned unchanged."""
    try:
        import openai

        if isinstance(openai.AsyncOpenAI, type) and isinstance(client, openai.AsyncOpenAI):
            return client.with_options(max_retries=0)
    except Exception:  # never let this helper break a request
        pass
    return client


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
    call_kwargs.setdefault("stream_options", {"include_usage": True})  # same option as the first pass
    stream = await no_retry_client(client).chat.completions.create(**call_kwargs)
    state.finish = None
    think_filter = StreamingThinkFilter()
    pass_usage: List[int] = []  # [prompt_tokens, completion_tokens] when the provider reported usage
    started = time.monotonic()

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
            usage = _read_usage(chunk)
            if usage:
                pass_usage = list(usage)
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
        _record_pass_usage(state, kwargs.get("model"), pass_usage, int((time.monotonic() - started) * 1000))


def _read_usage(chunk: Any) -> Optional[Tuple[int, int]]:
    """(prompt_tokens, completion_tokens) from a stream chunk, or None. Fakes without usage are fine."""
    usage = getattr(chunk, "usage", None)
    if not usage:
        return None
    prompt, completion = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
    if isinstance(prompt, int) and isinstance(completion, int) and not isinstance(prompt, bool):
        return prompt, completion
    return None


def _record_pass_usage(state: StreamState, model: Any, pass_usage: List[int], duration_ms: int) -> None:
    """Accumulate on the state and record once for this pass. Never raises."""
    if len(pass_usage) != 2 or not model:
        return
    state.prompt_tokens += pass_usage[0]
    state.completion_tokens += pass_usage[1]
    try:
        from backend.services.usage import record_usage

        record_usage(str(model), pass_usage[0], pass_usage[1], duration_ms=duration_ms)
    except Exception as e:  # telemetry must never break a chat turn
        logger.debug("Could not record usage for a streamed pass: %s", e)


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
    then ("result", result_dict). Falls back to the normal post-hoc event when no early signal fired.

    Once a change is saved, the orchestrator gets stream_watch.POST_COMMIT_TIMEOUT_S to return. If it is
    late (for example a database write waiting on an exhausted pool) or raises, the result is rebuilt from
    the committed payload so the reply and done event still go out. Logs:
      ERROR post_commit_timeout request_id=<id> waited_s=<n.n> limit_s=<n.n>
      ERROR post_commit_error request_id=<id> error=<Type: message>
    """
    trace_id = kwargs.pop("trace_id", None) or kwargs.get("request_id") or "-"
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    token = set_commit_listener(queue.put_nowait)
    try:
        task = asyncio.ensure_future(handle_message(**kwargs))
    finally:
        reset_commit_listener(token)

    emitted = False
    committed_payload: Optional[Dict[str, Any]] = None
    committed_at = 0.0
    timed_out = False
    getter: Optional["asyncio.Future[Dict[str, Any]]"] = None
    try:
        while not task.done():
            if getter is None:
                getter = asyncio.ensure_future(queue.get())
            wait_s = max(0.0, stream_watch.POST_COMMIT_TIMEOUT_S - (time.monotonic() - committed_at)) if emitted else None
            await asyncio.wait({task, getter}, timeout=wait_s, return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                payload = getter.result()
                evt = committed_event(payload)
                getter = None
                if evt and not emitted:
                    emitted, committed_payload, committed_at = True, payload, time.monotonic()
                    yield ("committed", evt)
            elif emitted and not task.done() and time.monotonic() - committed_at >= stream_watch.POST_COMMIT_TIMEOUT_S:
                timed_out = True
                break
        while not queue.empty() and not emitted:
            payload = queue.get_nowait()
            evt = committed_event(payload)
            if evt:
                emitted, committed_payload = True, payload
                yield ("committed", evt)
    finally:
        if getter is not None and not getter.done():
            getter.cancel()
        if not task.done():
            # Generator closed while the orchestrator is still running: retrieve and log its outcome.
            task.add_done_callback(stream_watch.late_outcome_logger(str(trace_id)))
    if timed_out:
        logger.error(
            "post_commit_timeout request_id=%s waited_s=%.1f limit_s=%.1f",
            trace_id, time.monotonic() - committed_at, stream_watch.POST_COMMIT_TIMEOUT_S,
        )
        yield ("result", stream_watch.degraded_result(committed_payload, "post_commit_timeout"))
        return
    try:
        result = task.result()
    except Exception as err:
        if committed_payload is None:
            raise
        logger.error("post_commit_error request_id=%s error=%s: %s", trace_id, type(err).__name__, err)
        result = stream_watch.degraded_result(committed_payload, "post_commit_error")
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

LAST_MESSAGE = "last"


async def load_continue_target(
    pool: Any, message_id_raw: Any, owner_id: Optional[str], conversation_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """The caller's own assistant message to continue plus the few messages before it, or None.

    `message_id_raw` is a message id, or "last": a message that has just finished streaming has no id on
    the client yet (it is saved in the background), so "last" means the newest assistant message of
    `conversation_id`. Ownership is checked the same way in both cases.
    """
    raw = str(message_id_raw or "").strip().lower()
    is_last = raw == LAST_MESSAGE
    if not (pool and owner_id and (raw.isdigit() or (is_last and conversation_id))):
        return None
    try:
        async with pool.acquire() as conn:
            if is_last:
                row = await conn.fetchrow(
                    "SELECT m.id, m.role, m.content, m.conversation_id FROM messages m "
                    "JOIN conversations c ON m.conversation_id = c.id "
                    "WHERE c.id = $1::uuid AND (c.user_id = $2 OR (c.guest_id = $2 AND c.user_id IS NULL)) "
                    "AND m.role = 'assistant' AND COALESCE(m.content, '') <> '' "
                    "ORDER BY m.id DESC LIMIT 1",
                    str(conversation_id), owner_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT m.id, m.role, m.content, m.conversation_id FROM messages m "
                    "JOIN conversations c ON m.conversation_id = c.id "
                    "WHERE m.id = $1 AND (c.user_id = $2 OR (c.guest_id = $2 AND c.user_id IS NULL))",
                    int(raw), owner_id,
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


async def _append_to_message(
    pool: Any, message_id: Any, new_text: str, truncated: bool, status: Optional[str],
    expected_content: Optional[str] = None,
) -> bool:
    """Append `new_text`. With `expected_content` the append is a compare-and-set: it only applies when the
    message still has that text, so two concurrent continues cannot both append. False when not applied."""
    if not (pool and new_text):
        return False
    try:
        async with pool.acquire() as conn:
            if expected_content is None:
                await conn.execute("UPDATE messages SET content = content || $2 WHERE id = $1", message_id, new_text)
            else:
                res = await conn.execute(
                    "UPDATE messages SET content = content || $2 WHERE id = $1 AND content = $3",
                    message_id, new_text, expected_content,
                )
                if isinstance(res, str) and res.strip().endswith(" 0"):
                    logger.warning("Message %s changed while continuing; the continuation was not appended", message_id)
                    return False
            await mark_message_state(conn, message_id, truncated, status)
            if not truncated and not status:
                try:
                    await conn.execute(
                        "UPDATE messages SET is_truncated = FALSE, stream_status = NULL WHERE id = $1", message_id
                    )
                except Exception:
                    pass
        return True
    except Exception as e:
        logger.error("Could not append continued text to message %s: %s", message_id, e)
        return False


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
    conversation_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Resume a saved assistant message: stream only the NEW text and append it to that message."""
    target = await load_continue_target(pool, message_id_raw, owner_id, conversation_id)
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
        await _append_to_message(pool, target["id"], state.full_text, True, STATUS_INTERRUPTED, target["content"])
        yield friendly_error_event(partial=state.full_text)
        return

    if state.disconnected:
        await _append_to_message(pool, target["id"], state.full_text, True, STATUS_INTERRUPTED, target["content"])
        return
    # No visible new text means the answer is still unfinished; keep it flagged so Continue stays available.
    still_truncated = state.truncated or not state.full_text.strip()
    await _append_to_message(
        pool, target["id"], state.full_text, still_truncated, STATUS_TRUNCATED if still_truncated else None,
        target["content"],
    )
    yield sse({
        "type": "done", "conversation_id": target["conversation_id"], "skill_used": "chat",
        "is_truncated": still_truncated, "continued_message_id": target["id"],
    })


# Saved Career profile in chat context (N-010): lives in chat_profile_context.py (file-size limit);
# re-exported here so existing imports and tests keep working.
from backend.services.chat_profile_context import (  # noqa: E402,F401
    _ordinal,
    format_candidate_profile,
    load_candidate_profile_context,
)


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
