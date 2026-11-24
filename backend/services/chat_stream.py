"""
Compass — Chat SSE Streaming Engine.

Handles asynchronous token-by-token streaming, tool-bypass routing,
concurrent context pre-fetching, and resilient background conversation persistence.
"""

import asyncio
import functools
import json
import logging
import sys
import time
import uuid
from datetime import date
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

import openai
from fastapi import Request
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from backend.config import get_settings
from backend.memory import conversations
from backend.memory.db import get_pool as db_get_pool
from backend.models import StreamChatRequest
import backend.orchestrator as orchestrator
from backend.router import TOOLS, message_needs_tools
from backend.router_helpers import (
    is_greeting_intent,
    is_long_form_request,
    is_schedule_or_agent_intent,
    is_tavily_verification_intent,
    is_pending_action_confirm,
    is_pending_action_cancel,
    is_chat_delete_intent,
    is_undo_request,
)
from backend.services.chat_idempotency import committed_event, normalize_request_id, peek_replay, replay_events
from backend.services.chat_fastpath import GREETING_REPLY, apply_router_extra_body, is_greeting_fastpath
from backend.services.task_intent import is_intake_intent
from backend.services.task_time import local_today, pick_timezone
from backend.services.token_budget import stream_token_budget
from backend.services.usage import record_usage
from backend.services.stream_claim_guard import StreamClaimGuard
from backend.services.chat_stream_extras import (
    DIRECT_ANSWER_RULE,
    GENERIC_ERROR_MESSAGE,
    SPECIALIST_FAILED_MESSAGE,
    STATUS_INTERRUPTED,
    STATUS_TRUNCATED,
    STREAM_REQUEST_TIMEOUT_S,
    StreamState,
    continuation_events,
    continue_message_events,
    friendly_error_event,
    load_candidate_profile_context,
    mark_message_state,
    no_retry_client,
    orchestrate_with_early_commit,
    run_web_fallback,
    should_search_web,
    specialist_answer_events,
    sse,
    status_event,
    text_pass_events,
)

logger = logging.getLogger("compass.services.chat_stream")

get_pool = db_get_pool


from backend.services.streaming_filter import StreamingThinkFilter
from backend.services.stream_watch import StreamTrace, timed_acquire


async def _resolve_pool():
    """Resolve database pool, honoring any monkeypatches on backend.services.chat_stream or backend.routers.chat in unit tests."""
    this_mod = sys.modules.get("backend.services.chat_stream")
    if this_mod and getattr(this_mod, "get_pool", None) is not db_get_pool:
        res = this_mod.get_pool()
        if asyncio.iscoroutine(res):
            return await res
        return res

    chat_mod = sys.modules.get("backend.routers.chat")
    if chat_mod and getattr(chat_mod, "get_pool", None) is not db_get_pool:
        res = chat_mod.get_pool()
        if asyncio.iscoroutine(res):
            return await res
        return res

    return await db_get_pool()


def _get_stream_client(_settings: Any) -> Any:
    """Model client for streaming chat (kept identical to the previous inline selection)."""
    if not isinstance(openai.AsyncOpenAI, type) or hasattr(openai.AsyncOpenAI, "_mock_return_value"):
        return openai.AsyncOpenAI(
            api_key=_settings.NEBIUS_API_KEY,
            base_url=_settings.NEBIUS_BASE_URL,
            timeout=30.0,
        )
    from backend.router import get_openai_client
    return get_openai_client()


def _format_empty_model_error(result: Optional[dict] = None) -> str:
    s = get_settings()
    key = s.NEBIUS_API_KEY or ""
    if not key or key.startswith("your_nebius") or key.startswith("mock") or key in ("mock", "mock-key-not-used-in-tests"):
        return "Model key missing or invalid. See the setup notes"
    if result and result.get("error"):
        return str(result["error"])
    return "The model returned an empty response. Please retry."


async def persist_stream_messages(
    conv_id: str,
    message: str,
    final_text: str,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    skill_label: str = "chat",
    evidence: Optional[Dict[str, Any]] = None,
    verifiable: Optional[bool] = None,
    is_truncated: bool = False,
    stream_status: Optional[str] = None,
    request_id: Optional[str] = None,
) -> bool:
    """Persist user prompt and assistant response asynchronously after SSE stream completion.

    Ensures failures are explicitly caught and logged with full context rather
    than silently dropped. `is_truncated` / `stream_status` are stored on the assistant message so a
    reload still shows that the answer was cut short or interrupted.
    """
    if not final_text:
        logger.debug("Skipping stream persistence for empty response in conv=%s", conv_id)
        return False

    try:
        pool = await _resolve_pool()
        if not pool:
            logger.error(
                "Database connection pool unavailable; failed to persist streamed message for conv=%s, user=%s",
                conv_id,
                user_id or guest_id or "anonymous",
            )
            return False

        async with timed_acquire(pool, request_id, "persist_stream_messages") as conn:
            real_cid = await conversations.get_or_create_conversation(
                conn, conv_id, user_id=user_id, guest_id=guest_id
            )
            await conversations.add_message(conn, real_cid, role="user", content=message)
            saved = await conversations.add_message(
                conn, real_cid, role="assistant", content=final_text, skill_called=skill_label, evidence=evidence, verifiable=verifiable
            )
            if is_truncated or stream_status:
                await mark_message_state(
                    conn, saved.get("id") if isinstance(saved, dict) else None, is_truncated, stream_status
                )
        logger.debug("Successfully persisted streamed conversation message for conv=%s (real_cid=%s)", conv_id, real_cid)
        return True
    except Exception as save_err:
        logger.error(
            "Failed to persist streamed messages for conversation %s: %s",
            conv_id,
            save_err,
            exc_info=True,
        )
        return False


def _schedule_stream_persistence(
    conv_id: str,
    message: str,
    final_text: str,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    skill_label: str = "chat",
    evidence: Optional[Dict[str, Any]] = None,
    verifiable: Optional[bool] = None,
    is_truncated: bool = False,
    stream_status: Optional[str] = None,
    request_id: Optional[str] = None,
) -> asyncio.Task:
    """Schedule stream persistence as an async background task with an exception handler."""
    task = asyncio.create_task(
        persist_stream_messages(
            request_id=request_id,
            conv_id=conv_id,
            message=message,
            final_text=final_text,
            user_id=user_id,
            guest_id=guest_id,
            skill_label=skill_label,
            evidence=evidence,
            verifiable=verifiable,
            is_truncated=is_truncated,
            stream_status=stream_status,
        )
    )

    def _on_done(t: asyncio.Task) -> None:
        try:
            if not t.cancelled() and t.exception():
                logger.error("Unhandled exception in stream persistence task: %s", t.exception())
        except Exception as cb_err:
            logger.error("Error checking stream persistence task outcome: %s", cb_err)

    task.add_done_callback(_on_done)
    return task


async def stream_chunks(text: str) -> AsyncGenerator[str, None]:
    """Yield natural word/subword chunks to simulate conversational delivery."""
    if not text:
        return
    cursor = 0
    while cursor < len(text):
        next_space = text.find(" ", cursor)
        if next_space != -1 and next_space - cursor <= 12:
            take = next_space - cursor + 1
        else:
            take = min(8, len(text) - cursor)
        yield text[cursor:cursor + take]
        cursor += take


def generate_chat_events(
    req: StreamChatRequest,
    request: Request,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Traced entry point: logs stream start/end and runs the silent-stream watchdog around the real generator."""
    trace = StreamTrace(normalize_request_id(getattr(req, "request_id", None)), str(getattr(req, "conversation_id", None) or "") or None)
    return cast(AsyncGenerator[str, None], trace.run(_generate_chat_events(req, request, user_id, guest_id, trace.request_id), request))


async def _generate_chat_events(
    req: StreamChatRequest,
    request: Request,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events (SSE) for conversational and tool-dispatching chat requests."""
    _settings = get_settings()
    _persist_bg = functools.partial(_schedule_stream_persistence, request_id=trace_id)
    conv_id = req.conversation_id or str(uuid.uuid4())
    message = req.message.strip()
    req_tone = getattr(req, "tone", None)
    req_include_demo = bool(getattr(req, "include_demo", False))
    effective_tone = "detailed" if (req_tone == "balanced" and is_long_form_request(message)) else req_tone
    yield ": ping\n\n"

    specialist_id = req.get_specialist_id() if hasattr(req, "get_specialist_id") else None
    if specialist_id:
        from backend.agents.specialist_registry import validate_specialist_id
        valid_id = validate_specialist_id(specialist_id)
        if not valid_id:
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Invalid specialist ID: {specialist_id}', 'terminal': True})}\n\n"
            return

        from backend.agents.specialist import run_specialist_task
        pool = await _resolve_pool()
        yield status_event("thinking", f"Gathering {valid_id.replace('-', ' ')} context…")
        try:
            spec_result = await run_specialist_task(
                capability=valid_id, user_goal=message, pool=pool, user_id=user_id or guest_id,
                include_demo=req_include_demo, defer_synthesis=True,
            )
        except Exception as spec_err:
            logger.error("Specialist %s failed before streaming: %s", valid_id, spec_err, exc_info=True)
            yield sse({'type': 'error', 'detail': SPECIALIST_FAILED_MESSAGE, 'can_retry': True, 'terminal': True})
            return
        spec_state = StreamState()
        spec_header = spec_result.get("task_created_header") or ""
        try:
            spec_settings = _settings
            spec_key = spec_settings.NEBIUS_API_KEY or ""
            spec_use_model = bool(spec_key) and not spec_key.startswith("your_nebius") and spec_key not in ("mock", "mock-key-not-used-in-tests")
            spec_client = _get_stream_client(spec_settings) if spec_use_model else None
            async for spec_evt in specialist_answer_events(
                client=spec_client, settings=spec_settings, request=request, spec_result=spec_result,
                user_goal=message, state=spec_state, max_tokens=int(getattr(spec_settings, "MAX_SYNTHESIS_TOKENS", 8192)),
                use_model=spec_use_model,
            ):
                yield spec_evt
        except Exception as spec_stream_err:
            logger.error("Specialist %s stream failed: %s", valid_id, spec_stream_err, exc_info=True)
            if not spec_header:
                yield friendly_error_event(partial=spec_state.full_text, detail=SPECIALIST_FAILED_MESSAGE)
                return
            spec_state.failed = True
        if spec_state.failed and spec_header:
            # A task was already created and announced. Never answer with a retryable error (Retry would
            # create it again): finish normally, with the plain summary when the model wrote nothing.
            if spec_state.full_text.strip():
                spec_state.continuation_failed = True  # partial text kept: flag it as cut short
            else:
                spec_fallback = str(spec_result.get("summary") or "")
                if spec_fallback.strip():
                    yield sse({"type": "token", "value": spec_fallback})
                    spec_state.full_text = spec_fallback
            spec_state.failed = False
        response_text = (spec_header + spec_state.full_text).strip() if (spec_header or spec_state.full_text.strip()) else ""
        spec_truncated = spec_state.truncated and not spec_state.failed
        spec_status = STATUS_TRUNCATED if spec_truncated else (STATUS_INTERRUPTED if (spec_state.failed or spec_state.disconnected) else None)

        try:
            if pool and response_text:
                async with timed_acquire(pool, trace_id, "persist_specialist") as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=f"[{valid_id}] {message}")
                    saved_spec = await conversations.add_message(conn, real_cid, role="assistant", content=response_text, skill_called=f"specialist_{valid_id}")
                    await mark_message_state(conn, saved_spec.get("id") if isinstance(saved_spec, dict) else None, spec_truncated or bool(spec_status), spec_status)
                    conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist specialist message history in stream: {e}")

        if spec_state.disconnected:
            return
        if spec_state.failed:
            err_payload: dict[str, Any] = {'type': 'error', 'detail': SPECIALIST_FAILED_MESSAGE, 'can_retry': True, 'terminal': True}
            if response_text:
                err_payload['partialResponse'] = response_text
            yield sse(err_payload)
            return
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': f'specialist_{valid_id}', 'is_truncated': spec_truncated})}\n\n"
        return

    continue_msg_id = getattr(req, "continue_message_id", None)
    if continue_msg_id:
        # Continue mode: resume a saved assistant message and stream only the new text.
        from backend.persona import build_persona_system_prompt as _persona_prompt

        try:
            cont_pool = await _resolve_pool()
            cont_today = local_today(pick_timezone(getattr(req, "tz", None), None)).isoformat()
            cont_sys_prompt = _persona_prompt(
                profile_facts=None,
                extra_context=f"Today's date is {cont_today}.",
                tone=effective_tone,
                parked_thoughts=None,
                conv_mode=getattr(req, "mode", None),
            )
            yield status_event("thinking", "Picking up where the answer stopped…")
            async for cont_evt in continue_message_events(
                client=_get_stream_client(_settings), settings=_settings, request=request, pool=cont_pool,
                owner_id=user_id or guest_id, message_id_raw=continue_msg_id, system_prompt=cont_sys_prompt,
                max_tokens=stream_token_budget(effective_tone, int(getattr(_settings, "MAX_SYNTHESIS_TOKENS", 8192)))[0],
                conversation_id=getattr(req, "conversation_id", None),
            ):
                yield cont_evt
        except Exception as cont_err:
            logger.error("Continue mode failed: %s", cont_err, exc_info=True)
            yield friendly_error_event(detail=GENERIC_ERROR_MESSAGE)
        return

    replayed = await peek_replay(
        await _resolve_pool(), user_id or guest_id or "default_user", normalize_request_id(getattr(req, "request_id", None))
    )
    if replayed:
        for replay_evt in replay_events(replayed, conv_id):
            yield replay_evt
        return

    if is_greeting_fastpath(req, message):
        # Pure greeting in a plain chat turn: answer at once, no model call.
        yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'stage': 'thinking', 'label': 'Understanding your request…'})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'value': GREETING_REPLY})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'}, default=str)}\n\n"
        _persist_bg(conv_id, message, GREETING_REPLY, user_id, guest_id, "chat")
        return

    stream_start = time.perf_counter()
    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    yield f"data: {json.dumps({'type': 'status', 'stage': 'thinking', 'label': 'Understanding your request…'})}\n\n"

    needs_tools = message_needs_tools(message)

    history_items: List[dict[str, str]] = []
    memory_context = ""
    profile_facts: dict = {}
    parked_items: list = []
    try:
        pool = await _resolve_pool()
        if pool:
            async def _load_history():
                if not req.conversation_id:
                    return []
                async with pool.acquire() as conn:
                    return await conversations.get_recent_messages(conn, req.conversation_id, limit=6)

            async def _load_prior():
                async with pool.acquire() as conn:
                    return await conversations.get_cross_conversation_memory(
                        conn, exclude_conversation_id=req.conversation_id, user_id=user_id, guest_id=guest_id, limit=6
                    )

            async def _load_tasks():
                if not needs_tools or not user_id:
                    return []
                async with pool.acquire() as conn:
                    return await conn.fetch(
                        "SELECT title, domain, due_date, status, priority FROM tasks WHERE status != 'completed' AND deleted_at IS NULL AND user_id = $1 AND ($2::boolean OR COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%') ORDER BY due_date ASC NULLS LAST LIMIT 8",
                        user_id,
                        req_include_demo,
                    )

            async def _load_facts():
                try:
                    async with pool.acquire() as conn:
                        from backend.memory.profile import get_profile_facts
                        return await get_profile_facts(conn, user_id=user_id or "default_user")
                except Exception as e:
                    logger.warning("Could not pre-fetch profile facts (continuing gracefully): %s", e)
                    return {}

            async def _load_parked():
                try:
                    async with pool.acquire() as conn:
                        from backend.memory.parked import list_parked_thoughts
                        rows = await list_parked_thoughts(conn, user_id=user_id or "default_user", status="parked", limit=5)
                        return [r["text"] for r in rows if r.get("text")]
                except Exception as e:
                    logger.warning("Could not pre-fetch parked thoughts (continuing gracefully): %s", e)
                    return []

            gather_res: tuple[Any, ...] = await asyncio.gather(
                _load_history(), _load_prior(), _load_tasks(), _load_facts(), _load_parked(),
                load_candidate_profile_context(user_id or guest_id), return_exceptions=True
            )
            rows_h = gather_res[0]
            prior = gather_res[1]
            tasks_rows = gather_res[2]
            profile_facts = gather_res[3]
            parked_items = gather_res[4]
            candidate_ctx = gather_res[5]

            if not isinstance(profile_facts, dict):
                profile_facts = {}
            if not isinstance(parked_items, list):
                parked_items = []
            if isinstance(rows_h, list):
                for r in rows_h:
                    role = r.get("role", "user")
                    content = r.get("content", "")
                    if role in ("user", "assistant") and content:
                        history_items.append({"role": role, "content": content})
            mem_parts = []
            if isinstance(candidate_ctx, str) and candidate_ctx:
                mem_parts.append(candidate_ctx)
            if isinstance(prior, list) and prior:
                prior_text = "\n".join([f"- [{p.get('role', 'user')}]: {p.get('content', '')[:100]}" for p in prior])
                mem_parts.append(f"Past Chats Recall:\n{prior_text}")
            if isinstance(tasks_rows, list) and tasks_rows:
                tasks_text = "\n".join(
                    [f"- {t['title']} ({t['domain']}) | Due: {t['due_date'] or 'None'} | {t['priority']}" for t in tasks_rows]
                )
                mem_parts.append(f"Active Tasks & Deadlines (Prevent schedule clashes):\n{tasks_text}")
            if mem_parts:
                memory_context = "\n\n".join(mem_parts)
    except Exception as e:
        logger.debug("Pre-fetch failed: %s", e)
        profile_facts = {}
        parked_items = []

    stream = None
    full_text = ""
    try:
        client = _get_stream_client(_settings)

        profile_tz = profile_facts.get("timezone") if isinstance(profile_facts, dict) else None
        today_iso = local_today(pick_timezone(getattr(req, "tz", None), profile_tz)).isoformat()
        date_context = (
            f"Today's date is {today_iso}. When resolving dates without years (e.g. '30th oct'), use {today_iso[:4]}. "
            f"When the user asks follow-up questions, recalls earlier conversations, or asks to plan or schedule without clashing, "
            f"use the provided memory and active schedule context."
        )
        extra = date_context
        if memory_context:
            extra += f"\n\n[WORKSPACE MEMORY & PAST CONTEXT]:\n{memory_context}"

        from backend.persona import build_persona_system_prompt
        sys_prompt = build_persona_system_prompt(
            profile_facts=profile_facts if isinstance(profile_facts, dict) else None,
            extra_context=extra,
            tone=effective_tone,
            parked_thoughts=parked_items if isinstance(parked_items, list) and parked_items else None,
            conv_mode=getattr(req, "mode", None),
        )

        messages: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": sys_prompt},
        ]
        if history_items:
            messages.extend(cast(Any, history_items))
        messages.append({"role": "user", "content": message})

        tools: Any = cast(List[ChatCompletionToolParam], TOOLS) if needs_tools else None

        # Detect test mocks vs unconfigured placeholder keys
        is_mocked = (
            hasattr(client, "_mock_return_value")
            or hasattr(client, "_mock_wraps")
            or isinstance(getattr(client, "chat", None), (object,))
            and getattr(getattr(client, "chat", None), "completions", None).__class__.__name__ in ("MagicMock", "AsyncMock")
        )
        is_placeholder_key = (
            not _settings.NEBIUS_API_KEY
            or _settings.NEBIUS_API_KEY.startswith("your_nebius")
            or _settings.NEBIUS_API_KEY in ("mock", "mock-key-not-used-in-tests")
        )

        target_msg_id = getattr(req, "target_message_id", None)
        target_msg_content = getattr(req, "target_message_content", None)

        is_safety_intent = (
            is_pending_action_confirm(message)
            or is_pending_action_cancel(message)
            or is_chat_delete_intent(message)[0]
            or is_undo_request(message)
            or is_intake_intent(message)
        )

        if (not is_mocked and is_placeholder_key) or is_schedule_or_agent_intent(message) or is_tavily_verification_intent(message) or is_safety_intent:
            result: dict[str, Any] = {}
            early_committed = False
            async for orch_kind, orch_val in orchestrate_with_early_commit(
                orchestrator.handle_message,
                trace_id=trace_id,
                conversation_id=conv_id,
                request_id=getattr(req, "request_id", None),
                tz=getattr(req, "tz", None),
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                tone=effective_tone,
                include_demo=req_include_demo,
                persist=False,
                target_message_id=target_msg_id,
                target_message_content=target_msg_content,
                pool=pool,
                conv_mode=getattr(req, "mode", None),
            ):
                if orch_kind == "committed":
                    early_committed = True
                    yield orch_val
                else:
                    result = orch_val
            response_text = result.get("response", "")
            committed_evt = committed_event(result)
            if committed_evt and not early_committed:
                yield committed_evt
            skill_used = result.get("skill_used") or "agent"
            thought = (result.get("data") or {}).get("thought") if isinstance(result.get("data"), dict) else None

            if thought:
                yield f"data: {json.dumps({'type': 'thought', 'value': thought})}\n\n"

            if not response_text.strip():
                if not is_greeting_intent(message):
                    yield f"data: {json.dumps({'type': 'error', 'detail': _format_empty_model_error(result), 'can_retry': True})}\n\n"
                    return
                response_text = "How can I help you today?"

            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est, duration_ms=result.get("routing_latency_ms"))

            is_first = True
            async for chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"

            done_payload: dict[str, Any] = {
                'type': 'done',
                'conversation_id': result.get('conversation_id', conv_id),
                'skill_used': skill_used,
                'verifiable': result.get('verifiable', False),
            }
            raw_data = result.get('data')
            if isinstance(raw_data, list):
                valid_tasks = [t for t in raw_data if isinstance(t, dict) and 'title' in t][:6]
                if valid_tasks:
                    done_payload['tasks'] = valid_tasks
            elif isinstance(raw_data, dict):
                done_payload['data'] = raw_data
                evidence = raw_data.get('evidence')
                if evidence:
                    done_payload['evidence'] = evidence
                if 'pending_action' in raw_data:
                    done_payload['pending_action'] = raw_data['pending_action']
                if 'can_undo' in raw_data:
                    done_payload['can_undo'] = raw_data['can_undo']
            if result.get('is_truncated') or (isinstance(raw_data, dict) and raw_data.get('is_truncated')):
                done_payload['is_truncated'] = True
            yield f"data: {json.dumps(done_payload, default=str)}\n\n"
            _persist_bg(
                conv_id,
                message,
                response_text,
                user_id,
                guest_id,
                skill_used,
                evidence=done_payload.get('evidence'),
                verifiable=result.get('verifiable', False),
                is_truncated=bool(done_payload.get('is_truncated')),
                stream_status=STATUS_TRUNCATED if done_payload.get('is_truncated') else None,
            )
            return

        logger.info("Serving chat stream request with model=%s", _settings.ROUTER_MODEL)
        max_synth_budget = int(getattr(_settings, "MAX_SYNTHESIS_TOKENS", 8192))
        stream_max_tokens, _ = stream_token_budget(effective_tone, max_synth_budget)

        call_kwargs: dict[str, Any] = {
            "model": _settings.ROUTER_MODEL,
            "messages": messages,
            "max_tokens": stream_max_tokens,
            "temperature": 0.7,
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": STREAM_REQUEST_TIMEOUT_S,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"
        apply_router_extra_body(call_kwargs, _settings)

        try:
            stream = cast(
                openai.AsyncStream[ChatCompletionChunk],
                await no_retry_client(client).chat.completions.create(**call_kwargs),
            )
        except Exception as create_err:
            logger.warning("Upstream stream creation failed: %s, falling back to orchestrator", create_err)
            result = await orchestrator.handle_message(
                conversation_id=conv_id,
                request_id=getattr(req, "request_id", None),
                tz=getattr(req, "tz", None),
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
                tone=effective_tone,
                include_demo=req_include_demo,
                conv_mode=getattr(req, "mode", None),
            )
            response_text = result.get("response", "")
            committed_evt = committed_event(result)
            if committed_evt:
                yield committed_evt
            skill_used = result.get("skill_used") or "chat"
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est, duration_ms=result.get("routing_latency_ms"))

            is_first = True
            async for text_chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': text_chunk})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _persist_bg(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        full_text = ""
        emitted_text = ""
        thinking_sent = False
        tool_call_detected = False
        usage_data = None
        last_finish_reason: Optional[str] = None
        cont_failed = False
        think_filter = StreamingThinkFilter()
        claim_guard = StreamClaimGuard()
        accumulated_tool_calls: Dict[int, Dict[str, str]] = {}

        try:
            async for stream_chunk in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected from chat SSE stream; closing upstream stream.")
                    if hasattr(stream, "aclose"):
                        await stream.aclose()
                    full_text += think_filter.flush()
                    _persist_bg(
                        conv_id, message, full_text.strip(), user_id, guest_id, "chat",
                        is_truncated=True, stream_status=STATUS_INTERRUPTED,
                    )
                    return

                if hasattr(stream_chunk, "usage") and stream_chunk.usage:
                    usage_data = stream_chunk.usage

                choices = stream_chunk.choices or []
                if choices:
                    delta = choices[0].delta
                    finish_reason = choices[0].finish_reason
                    if finish_reason:
                        last_finish_reason = finish_reason

                    tcs = getattr(delta, "tool_calls", None) if delta else None
                    if tcs:
                        tool_call_detected = True
                        for tc in tcs:
                            idx = getattr(tc, "index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {"name": "", "arguments": ""}
                            fn = getattr(tc, "function", None)
                            if fn:
                                if getattr(fn, "name", None):
                                    accumulated_tool_calls[idx]["name"] += fn.name
                                if getattr(fn, "arguments", None):
                                    accumulated_tool_calls[idx]["arguments"] += fn.arguments

                    if finish_reason in ("tool_calls", "function_call") or (tool_call_detected and finish_reason):
                        tool_call_detected = True
                        if hasattr(stream, "aclose"):
                            await stream.aclose()
                        break

                    # Private reasoning is never shown, but tell the user the model is working.
                    reasoning_val = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                    if isinstance(reasoning_val, str) and reasoning_val and not emitted_text and not thinking_sent:
                        thinking_sent = True
                        yield status_event("thinking", "Thinking it through…")

                    # Strip reasoning_content and <think> blocks from user SSE token output
                    token = (delta.content if delta else None) or ""
                    if token:
                        filtered_token = think_filter.process(token)
                        if filtered_token:
                            if claim_guard.blocked:
                                continue
                            if not emitted_text:
                                yield f"data: {json.dumps({'type': 'status', 'stage': 'generating', 'label': 'Generating response…'})}\n\n"
                            full_text += filtered_token
                            emitted_text += filtered_token
                            yield f"data: {json.dumps({'type': 'token', 'value': filtered_token})}\n\n"
                            if rep := claim_guard.observe(filtered_token):
                                yield f"data: {json.dumps({'type': 'replace', 'value': rep})}\n\n"
                                full_text = emitted_text = rep

            tail = "" if tool_call_detected else think_filter.flush()
            if tail and not claim_guard.blocked:
                if not emitted_text:
                    yield status_event("generating", "Generating response…")
                full_text += tail
                emitted_text += tail
                yield f"data: {json.dumps({'type': 'token', 'value': tail})}\n\n"
            if not tool_call_detected and (rep := claim_guard.finish()):
                yield f"data: {json.dumps({'type': 'replace', 'value': rep})}\n\n"
                full_text = emitted_text = rep

            # Bounded continuation if output token limit was reached (same prompt for every tone).
            # Skipped when the first pass produced no visible text: there is nothing to continue.
            cont_state = StreamState(
                full_text=full_text, emitted_text=emitted_text, finish=last_finish_reason, thinking_sent=thinking_sent
            )
            if not tool_call_detected and last_finish_reason == "length" and full_text.strip():
                async for cont_evt in continuation_events(
                    client,
                    {"model": _settings.ROUTER_MODEL, "max_tokens": max_synth_budget, "temperature": 0.7},
                    list(cast(Any, messages)),
                    cont_state,
                    request,
                    int(getattr(_settings, "MAX_CONTINUATION_ATTEMPTS", 2)),
                ):
                    yield cont_evt
                full_text, emitted_text = cont_state.full_text, cont_state.emitted_text
                last_finish_reason = cont_state.finish
                cont_failed = cont_state.continuation_failed
                if cont_state.disconnected:
                    _persist_bg(
                        conv_id, message, full_text.strip(), user_id, guest_id, "chat",
                        is_truncated=True, stream_status=STATUS_INTERRUPTED,
                    )
                    return

        except asyncio.CancelledError:
            logger.info("Chat SSE stream cancelled; closing upstream model stream.")
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            raise
        except Exception as stream_err:
            logger.error("Mid-stream failure reading model chunks: %s", stream_err, exc_info=True)
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            full_text += think_filter.flush() if not tool_call_detected else ""
            yield friendly_error_event(partial=full_text)
            _persist_bg(
                conv_id, message, full_text.strip(), user_id, guest_id, "chat",
                is_truncated=True, stream_status=STATUS_INTERRUPTED,
            )
            return

        if not tool_call_detected and not full_text.strip():
            # T-008: the first pass produced no visible text (hidden reasoning used the whole budget).
            # Retry the MODEL once with a short-reasoning hint rather than re-running the request through
            # the non-streaming orchestrator, whose task parser can save a mangled title.
            retry_state = StreamState(thinking_sent=thinking_sent)
            yield status_event("thinking", "Still working on it…")
            retry_messages = [dict(m) for m in cast(Any, messages)]
            if retry_messages and retry_messages[0].get("role") == "system":
                retry_messages[0]["content"] = str(retry_messages[0].get("content", "")) + DIRECT_ANSWER_RULE
            retry_kwargs: dict[str, Any] = {
                "model": _settings.ROUTER_MODEL, "messages": retry_messages,
                "max_tokens": max_synth_budget, "temperature": 0.7,
            }
            if tools:
                retry_kwargs["tools"] = tools
                retry_kwargs["tool_choice"] = "auto"
            try:
                async for retry_evt in text_pass_events(
                    client, retry_kwargs, retry_state, request, label="Generating response…", allow_tools=bool(tools)
                ):
                    yield retry_evt
                if (
                    not retry_state.disconnected and not retry_state.tool_call_detected
                    and retry_state.finish == "length" and retry_state.full_text.strip()
                ):
                    async for retry_cont_evt in continuation_events(
                        client,
                        {"model": _settings.ROUTER_MODEL, "max_tokens": max_synth_budget, "temperature": 0.7},
                        retry_messages, retry_state, request,
                        int(getattr(_settings, "MAX_CONTINUATION_ATTEMPTS", 2)),
                    ):
                        yield retry_cont_evt
            except Exception as retry_err:
                logger.warning("Retry after an empty first pass failed: %s", retry_err)
                if retry_state.full_text.strip():
                    retry_state.continuation_failed = True  # partial text kept: flag it as cut short
            if retry_state.disconnected:
                if retry_state.full_text.strip():
                    _persist_bg(
                        conv_id, message, retry_state.full_text.strip(), user_id, guest_id, "chat",
                        is_truncated=True, stream_status=STATUS_INTERRUPTED,
                    )
                return
            full_text, emitted_text = retry_state.full_text, retry_state.emitted_text
            last_finish_reason = retry_state.finish
            cont_failed = retry_state.continuation_failed
            if retry_state.tool_call_detected:
                tool_call_detected = True
                accumulated_tool_calls = retry_state.tool_calls

        if tool_call_detected:
            pre_routed_skill = None
            pre_routed_args = None
            if accumulated_tool_calls:
                first_tc = accumulated_tool_calls[min(accumulated_tool_calls.keys())]
                raw_name = (first_tc.get("name") or "").strip()
                raw_args_str = (first_tc.get("arguments") or "").strip()
                if raw_name:
                    from backend.services.chat_stream_helpers import validate_direct_tool_dispatch
                    dispatch_res = validate_direct_tool_dispatch(raw_name, raw_args_str)
                    if dispatch_res:
                        pre_routed_skill, pre_routed_args = dispatch_res


            if pre_routed_skill:
                if pre_routed_skill in ("search_web", "deep_research"):
                    q = (pre_routed_args or {}).get("query") or (pre_routed_args or {}).get("topic") or "sources"
                    yield f"data: {json.dumps({'type': 'status', 'stage': 'searching', 'label': f'Searching web for {q}…'})}\n\n"
                elif pre_routed_skill in ("verify_deadline", "detect_deadline_conflicts", "verify_with_tavily"):
                    yield f"data: {json.dumps({'type': 'status', 'stage': 'reading_sources', 'label': 'Verifying official deadline sources…'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'status', 'stage': 'reasoning', 'label': f'Executing {pre_routed_skill}…'})}\n\n"

            result = {}
            early_committed = False
            async for orch_kind, orch_val in orchestrate_with_early_commit(
                orchestrator.handle_message,
                trace_id=trace_id,
                conversation_id=conv_id,
                request_id=getattr(req, "request_id", None),
                tz=getattr(req, "tz", None),
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
                pre_routed_skill=pre_routed_skill,
                pre_routed_args=pre_routed_args,
                target_message_id=target_msg_id,
                target_message_content=target_msg_content,
                tone=effective_tone,
                include_demo=req_include_demo,
                conv_mode=getattr(req, "mode", None),
            ):
                if orch_kind == "committed":
                    early_committed = True
                    yield orch_val
                else:
                    result = orch_val
            response_text = result.get("response", "")
            committed_evt = committed_event(result)
            if committed_evt and not early_committed:
                yield committed_evt
            skill_used = result.get("skill_used") or "agent"

            # T-013: a memory lookup for an outside event (e.g. an official hackathon deadline) that found
            # nothing must search the web before replying. Falls through unchanged when search is off,
            # over budget, or returns nothing.
            if should_search_web(message, result):
                yield status_event("searching", "Checking the web for the official answer…")
                web_res = await run_web_fallback(message, pool)
                if web_res:
                    response_text = str(web_res.get("response") or response_text)
                    skill_used = "search_web"
                    result = {**result, "response": response_text, "skill_used": skill_used, "data": web_res.get("data")}
            thought = (result.get("data") or {}).get("thought") if isinstance(result.get("data"), dict) else None
            if thought:
                yield f"data: {json.dumps({'type': 'thought', 'value': thought})}\n\n"

            if not response_text.strip():
                if not is_greeting_intent(message):
                    yield f"data: {json.dumps({'type': 'error', 'detail': _format_empty_model_error(result), 'can_retry': True})}\n\n"
                    return
                response_text = "How can I help you today?"

            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est, duration_ms=result.get("routing_latency_ms"))

            if emitted_text and response_text.startswith(emitted_text):
                # Partial prefix matches — only emit the remaining suffix
                to_emit = response_text[len(emitted_text):]
                if to_emit:
                    yield f"data: {json.dumps({'type': 'token', 'value': to_emit})}\n\n"
            elif not emitted_text:
                # Nothing was streamed yet — emit full response as tokens
                is_first = True
                async for sc_token in stream_chunks(response_text):
                    if not is_first:
                        await asyncio.sleep(0.012)
                    is_first = False
                    yield f"data: {json.dumps({'type': 'token', 'value': sc_token})}\n\n"
            else:
                # Partial streamed text does NOT match orchestrator response —
                # send a replace event so the client discards the leaked markup
                # and replaces it with the clean tool-call response.
                yield f"data: {json.dumps({'type': 'replace', 'value': response_text})}\n\n"

            done_payload2: dict[str, Any] = {'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used}
            raw_data2 = result.get('data')
            if isinstance(raw_data2, list):
                valid_tasks2 = [t for t in raw_data2 if isinstance(t, dict) and 'title' in t][:6]
                if valid_tasks2:
                    done_payload2['tasks'] = valid_tasks2
            elif isinstance(raw_data2, dict):
                evidence2 = raw_data2.get('evidence')
                if evidence2:
                    done_payload2['evidence'] = evidence2
                if 'pending_action' in raw_data2:
                    done_payload2['pending_action'] = raw_data2['pending_action']
                if 'can_undo' in raw_data2:
                    done_payload2['can_undo'] = raw_data2['can_undo']
            if result.get('is_truncated') or (isinstance(raw_data2, dict) and raw_data2.get('is_truncated')):
                done_payload2['is_truncated'] = True
            yield f"data: {json.dumps(done_payload2, default=str)}\n\n"
            _persist_bg(
                conv_id, message, response_text, user_id, guest_id, skill_used,
                evidence=done_payload2.get('evidence'),
                is_truncated=bool(done_payload2.get('is_truncated')),
                stream_status=STATUS_TRUNCATED if done_payload2.get('is_truncated') else None,
            )
            return

        if not full_text.strip():
            # Still nothing after one retry: answer a plain greeting, otherwise tell the user and offer Retry.
            if not is_greeting_intent(message):
                yield f"data: {json.dumps({'type': 'error', 'detail': _format_empty_model_error(None), 'can_retry': True}, default=str)}\n\n"
                return
            greeting_text = "How can I help you today?"
            async for greet_token in stream_chunks(greeting_text):
                yield f"data: {json.dumps({'type': 'token', 'value': greet_token})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'}, default=str)}\n\n"
            _persist_bg(conv_id, message, greeting_text, user_id, guest_id, "chat")
            return

        final_truncated = last_finish_reason == "length" or cont_failed
        final_skill = "chat"

        # T-013: a plain-chat reply that says "I don't have that" for an outside-event question gets a web
        # search and the searched answer replaces it (search off / over budget / nothing found: unchanged).
        if should_search_web(message, text=full_text):
            yield status_event("searching", "Checking the web for the official answer…")
            web_final = await run_web_fallback(message, pool)
            web_text = str((web_final or {}).get("response") or "")
            if web_text.strip():
                yield f"data: {json.dumps({'type': 'replace', 'value': web_text})}\n\n"
                full_text = web_text
                final_truncated = False
                final_skill = "search_web"

        _persist_bg(
            conv_id, message, full_text, user_id, guest_id, final_skill,
            is_truncated=final_truncated, stream_status=STATUS_TRUNCATED if final_truncated else None,
        )

        total_dur_ms = int((time.perf_counter() - stream_start) * 1000)
        if usage_data:
            record_usage(_settings.ROUTER_MODEL, getattr(usage_data, "prompt_tokens", 30), getattr(usage_data, "completion_tokens", 15), duration_ms=total_dur_ms)
        else:
            prompt_est = len(message.split()) * 3
            completion_est = len(full_text.split())
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est, duration_ms=total_dur_ms)

        done_payload_final: dict[str, Any] = {'type': 'done', 'conversation_id': conv_id, 'skill_used': final_skill}
        if final_truncated:
            done_payload_final['is_truncated'] = True
        yield f"data: {json.dumps(done_payload_final, default=str)}\n\n"

    except asyncio.CancelledError:
        logger.info("Chat SSE stream cancelled by client disconnect.")
        if full_text.strip():
            _persist_bg(
                conv_id, message, full_text.strip(), user_id, guest_id, "chat",
                is_truncated=True, stream_status=STATUS_INTERRUPTED,
            )
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        raise
    except Exception as e:
        logger.error("SSE stream outer error: %s", e, exc_info=True)
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        yield friendly_error_event(partial=full_text, detail=GENERIC_ERROR_MESSAGE)
        if full_text.strip():
            _persist_bg(
                conv_id, message, full_text.strip(), user_id, guest_id, "chat",
                is_truncated=True, stream_status=STATUS_INTERRUPTED,
            )
