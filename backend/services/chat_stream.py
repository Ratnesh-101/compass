"""
Compass — Chat SSE Streaming Engine.

Handles asynchronous token-by-token streaming, tool-bypass routing,
concurrent context pre-fetching, and resilient background conversation persistence.
"""

import asyncio
import json
import logging
import sys
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
from backend.services.usage import record_usage

logger = logging.getLogger("compass.services.chat_stream")

get_pool = db_get_pool


from backend.services.streaming_filter import StreamingThinkFilter


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


async def persist_stream_messages(
    conv_id: str,
    message: str,
    final_text: str,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    skill_label: str = "chat",
    evidence: Optional[Dict[str, Any]] = None,
    verifiable: Optional[bool] = None,
) -> bool:
    """Persist user prompt and assistant response asynchronously after SSE stream completion.

    Ensures failures are explicitly caught and logged with full context rather
    than silently dropped.
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

        async with pool.acquire() as conn:
            real_cid = await conversations.get_or_create_conversation(
                conn, conv_id, user_id=user_id, guest_id=guest_id
            )
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(
                conn, real_cid, role="assistant", content=final_text, skill_called=skill_label, evidence=evidence, verifiable=verifiable
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
) -> asyncio.Task:
    """Schedule stream persistence as an async background task with an exception handler."""
    task = asyncio.create_task(
        persist_stream_messages(
            conv_id=conv_id,
            message=message,
            final_text=final_text,
            user_id=user_id,
            guest_id=guest_id,
            skill_label=skill_label,
            evidence=evidence,
            verifiable=verifiable,
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


async def generate_chat_events(
    req: StreamChatRequest,
    request: Request,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events (SSE) for conversational and tool-dispatching chat requests."""
    _settings = get_settings()
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
        spec_result = await run_specialist_task(
            capability=valid_id, user_goal=message, pool=pool, user_id=user_id or guest_id
        )
        response_text = spec_result.get("summary", f"Specialist analysis completed for '{message}'.")

        try:
            if pool:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=f"[{valid_id}] {message}")
                    await conversations.add_message(conn, real_cid, role="assistant", content=response_text, skill_called=f"specialist_{valid_id}")
                    conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist specialist message history in stream: {e}")

        yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': f'specialist_{valid_id}'})}\n\n"
        return

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
                _load_history(), _load_prior(), _load_tasks(), _load_facts(), _load_parked(), return_exceptions=True
            )
            rows_h = gather_res[0]
            prior = gather_res[1]
            tasks_rows = gather_res[2]
            profile_facts = gather_res[3]
            parked_items = gather_res[4]

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
        if not isinstance(openai.AsyncOpenAI, type) or hasattr(openai.AsyncOpenAI, "_mock_return_value"):
            client = openai.AsyncOpenAI(
                api_key=_settings.NEBIUS_API_KEY,
                base_url=_settings.NEBIUS_BASE_URL,
                timeout=30.0,
            )
        else:
            from backend.router import get_openai_client
            client = get_openai_client()

        today_iso = date.today().isoformat()
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
        )

        if (not is_mocked and is_placeholder_key) or is_schedule_or_agent_intent(message) or is_tavily_verification_intent(message) or is_safety_intent:
            result = await orchestrator.handle_message(
                conversation_id=conv_id,
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
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "agent"
            thought = (result.get("data") or {}).get("thought") if isinstance(result.get("data"), dict) else None

            if thought:
                yield f"data: {json.dumps({'type': 'thought', 'value': thought})}\n\n"

            if not response_text.strip():
                if not is_greeting_intent(message):
                    yield f"data: {json.dumps({'type': 'error', 'detail': result.get('error') or 'The model returned an empty response. Please retry.', 'can_retry': True})}\n\n"
                    return
                response_text = "How can I help you today?"

            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

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
            _schedule_stream_persistence(
                conv_id,
                message,
                response_text,
                user_id,
                guest_id,
                skill_used,
                evidence=done_payload.get('evidence'),
                verifiable=result.get('verifiable', False),
            )
            return

        logger.info("Serving chat stream request with model=%s", _settings.ROUTER_MODEL)
        max_synth_budget = int(getattr(_settings, "MAX_SYNTHESIS_TOKENS", 8192))
        clean_tone = effective_tone
        hard_capped_tone = clean_tone in ("brief", "balanced")
        if clean_tone == "brief":
            stream_max_tokens = 90
        elif clean_tone == "balanced":
            stream_max_tokens = 250
        else:
            stream_max_tokens = max_synth_budget

        call_kwargs: dict[str, Any] = {
            "model": _settings.ROUTER_MODEL,
            "messages": messages,
            "max_tokens": stream_max_tokens,
            "temperature": 0.7,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        try:
            stream = cast(
                openai.AsyncStream[ChatCompletionChunk],
                await client.chat.completions.create(**call_kwargs),
            )
        except Exception as create_err:
            logger.warning("Upstream stream creation failed: %s, falling back to orchestrator", create_err)
            result = await orchestrator.handle_message(
                conversation_id=conv_id,
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
            skill_used = result.get("skill_used") or "chat"
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            is_first = True
            async for text_chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': text_chunk})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        full_text = ""
        emitted_text = ""
        tool_call_detected = False
        usage_data = None
        last_finish_reason: Optional[str] = None
        think_filter = StreamingThinkFilter()
        accumulated_tool_calls: Dict[int, Dict[str, str]] = {}

        try:
            async for stream_chunk in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected from chat SSE stream; closing upstream stream.")
                    if hasattr(stream, "aclose"):
                        await stream.aclose()
                    _schedule_stream_persistence(conv_id, message, full_text.strip(), user_id, guest_id, "chat")
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

                    # Do not stream private model reasoning tokens or internal deliberations to the user
                    reasoning_val = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                    if reasoning_val:
                        # Private reasoning suppressed from normal UI
                        pass

                    # Strip reasoning_content and <think> blocks from user SSE token output
                    token = (delta.content if delta else None) or ""
                    if token:
                        filtered_token = think_filter.process(token)
                        if filtered_token:
                            if not emitted_text:
                                yield f"data: {json.dumps({'type': 'status', 'stage': 'generating', 'label': 'Generating response…'})}\n\n"
                            full_text += filtered_token
                            emitted_text += filtered_token
                            yield f"data: {json.dumps({'type': 'token', 'value': filtered_token})}\n\n"

            # Bounded continuation if output token limit was reached
            continuation_attempts = 0
            max_cont_attempts = int(getattr(_settings, "MAX_CONTINUATION_ATTEMPTS", 2))
            while last_finish_reason == "length" and not tool_call_detected and not hard_capped_tone and continuation_attempts < max_cont_attempts:
                if await request.is_disconnected():
                    break
                continuation_attempts += 1
                logger.info("Direct stream hit token limit (length). Continuing response (%d/%d)...", continuation_attempts, max_cont_attempts)
                yield f"data: {json.dumps({'type': 'status', 'stage': 'generating', 'label': f'Continuing response ({continuation_attempts}/{max_cont_attempts})…'})}\n\n"

                cont_messages = list(messages)
                cont_messages.append({"role": "assistant", "content": full_text})
                cont_messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response was cut off by the token limit. "
                        "Continue generating EXACTLY where you left off. "
                        "Do not repeat prior paragraphs, table rows, citations, or greetings."
                    ),
                })
                cont_kwargs = {
                    "model": _settings.ROUTER_MODEL,
                    "messages": cont_messages,
                    "max_tokens": max_synth_budget,
                    "temperature": 0.7,
                    "stream": True,
                }
                try:
                    cont_stream = cast(
                        openai.AsyncStream[ChatCompletionChunk],
                        await client.chat.completions.create(**cont_kwargs),
                    )
                    last_finish_reason = None
                    cont_think_filter = StreamingThinkFilter()
                    async for c_chunk in cont_stream:
                        if await request.is_disconnected():
                            if hasattr(cont_stream, "aclose"):
                                await cont_stream.aclose()
                            _schedule_stream_persistence(conv_id, message, full_text.strip(), user_id, guest_id, "chat")
                            return
                        c_choices = c_chunk.choices or []
                        if c_choices:
                            c_delta = c_choices[0].delta
                            c_fr = c_choices[0].finish_reason
                            if c_fr:
                                last_finish_reason = c_fr
                            c_token = (c_delta.content if c_delta else None) or ""
                            if c_token:
                                c_filtered = cont_think_filter.process(c_token)
                                if c_filtered:
                                    full_text += c_filtered
                                    emitted_text += c_filtered
                                    yield f"data: {json.dumps({'type': 'token', 'value': c_filtered})}\n\n"
                except Exception as cont_err:
                    logger.warning("Continuation attempt %d failed: %s", continuation_attempts, cont_err)
                    break

        except asyncio.CancelledError:
            logger.info("Chat SSE stream cancelled; closing upstream model stream.")
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            raise
        except Exception as stream_err:
            logger.error("Mid-stream failure reading model chunks: %s", stream_err, exc_info=True)
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            yield f"data: {json.dumps({'type': 'error', 'detail': 'An internal error occurred while processing the stream.', 'terminal': True})}\n\n"
            _schedule_stream_persistence(conv_id, message, full_text.strip(), user_id, guest_id, "chat")
            return

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

            result = await orchestrator.handle_message(
                conversation_id=conv_id,
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
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "agent"
            thought = (result.get("data") or {}).get("thought") if isinstance(result.get("data"), dict) else None
            if thought:
                yield f"data: {json.dumps({'type': 'thought', 'value': thought})}\n\n"

            if not response_text.strip():
                if not is_greeting_intent(message):
                    yield f"data: {json.dumps({'type': 'error', 'detail': result.get('error') or 'The model returned an empty response. Please retry.', 'can_retry': True})}\n\n"
                    return
                response_text = "How can I help you today?"

            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

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
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used, evidence=done_payload2.get('evidence'))
            return

        if not full_text.strip():
            result = await orchestrator.handle_message(
                conversation_id=conv_id,
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
            skill_used = result.get("skill_used") or "chat"
            thought = (result.get("data") or {}).get("thought") if isinstance(result.get("data"), dict) else None
            if thought:
                yield f"data: {json.dumps({'type': 'thought', 'value': thought}, default=str)}\n\n"

            if not response_text.strip():
                if not is_greeting_intent(message):
                    yield f"data: {json.dumps({'type': 'error', 'detail': result.get('error') or 'The model returned an empty response. Please retry.', 'can_retry': True}, default=str)}\n\n"
                    return
                response_text = "How can I help you today?"

            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            is_first = True
            async for sc_token in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': sc_token})}\n\n"

            done_payload_orchestrator: dict[str, Any] = {'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used}
            raw_data_orch = result.get('data')
            if isinstance(raw_data_orch, dict):
                ev = raw_data_orch.get('evidence')
                if ev:
                    done_payload_orchestrator['evidence'] = ev
                if 'pending_action' in raw_data_orch:
                    done_payload_orchestrator['pending_action'] = raw_data_orch['pending_action']
                if 'can_undo' in raw_data_orch:
                    done_payload_orchestrator['can_undo'] = raw_data_orch['can_undo']
            if result.get('is_truncated') or (isinstance(raw_data_orch, dict) and raw_data_orch.get('is_truncated')):
                done_payload_orchestrator['is_truncated'] = True
            yield f"data: {json.dumps(done_payload_orchestrator, default=str)}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        _schedule_stream_persistence(conv_id, message, full_text, user_id, guest_id, "chat")

        if usage_data:
            record_usage(_settings.ROUTER_MODEL, getattr(usage_data, "prompt_tokens", 30), getattr(usage_data, "completion_tokens", 15))
        else:
            prompt_est = len(message.split()) * 3
            completion_est = len(full_text.split())
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

        done_payload_final: dict[str, Any] = {'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'}
        if last_finish_reason == "length":
            done_payload_final['is_truncated'] = True
        yield f"data: {json.dumps(done_payload_final, default=str)}\n\n"

    except asyncio.CancelledError:
        logger.info("Chat SSE stream cancelled by client disconnect.")
        if full_text.strip():
            _schedule_stream_persistence(conv_id, message, full_text.strip(), user_id, guest_id, "chat")
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        raise
    except Exception as e:
        logger.error("SSE stream outer error: %s", e, exc_info=True)
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        err_payload = {
            'type': 'error',
            'detail': 'Internal error occurred while processing stream.',
            'can_retry': True,
            'terminal': True,
        }
        if full_text.strip():
            err_payload['partialResponse'] = full_text.strip()
            _schedule_stream_persistence(conv_id, message, full_text.strip(), user_id, guest_id, "chat")
        yield f"data: {json.dumps(err_payload, default=str)}\n\n"
