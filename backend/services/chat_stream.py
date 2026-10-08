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
from typing import Any, AsyncGenerator, List, Optional, cast

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
from backend.services.usage import record_usage

logger = logging.getLogger("compass.services.chat_stream")

get_pool = db_get_pool


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
                conn, real_cid, role="assistant", content=final_text, skill_called=skill_label
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
        spec_result = await run_specialist_task(capability=valid_id, user_goal=message, pool=pool)
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
                if not needs_tools:
                    return []
                async with pool.acquire() as conn:
                    if user_id:
                        return await conn.fetch(
                            "SELECT title, domain, due_date, status, priority FROM tasks WHERE status != 'completed' AND (user_id IS NULL OR user_id = $1) ORDER BY due_date ASC NULLS LAST LIMIT 8",
                            user_id,
                        )
                    else:
                        return await conn.fetch(
                            "SELECT title, domain, due_date, status, priority FROM tasks WHERE status != 'completed' ORDER BY due_date ASC NULLS LAST LIMIT 8"
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

            rows_h, prior, tasks_rows, profile_facts, parked_items = await asyncio.gather(
                _load_history(), _load_prior(), _load_tasks(), _load_facts(), _load_parked(), return_exceptions=True
            )
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
    try:
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
            tone=getattr(req, "tone", None),
            parked_thoughts=parked_items if isinstance(parked_items, list) and parked_items else None,
            conv_mode=getattr(req, "mode", None),
        )

        messages: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": sys_prompt},
        ]
        if history_items:
            messages.extend(history_items)
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

        if not is_mocked and is_placeholder_key:
            result = await orchestrator.handle_message(
                conversation_id=req.conversation_id,
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "chat"
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            is_first = True
            async for chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        logger.info("Serving chat stream request with model=%s", _settings.ROUTER_MODEL)
        call_kwargs: dict[str, Any] = {
            "model": _settings.ROUTER_MODEL,
            "messages": messages,
            "max_tokens": 10000,
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
                conversation_id=req.conversation_id,
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "chat"
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            is_first = True
            async for chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        full_text = ""
        emitted_text = ""
        tool_call_detected = False
        usage_data = None

        try:
            async for chunk in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected from chat SSE stream; closing upstream stream.")
                    if hasattr(stream, "aclose"):
                        await stream.aclose()
                    return

                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data = chunk.usage

                choices = chunk.choices or []
                if choices:
                    delta = choices[0].delta
                    finish_reason = choices[0].finish_reason

                    if finish_reason in ("tool_calls", "function_call") or (delta and getattr(delta, "tool_calls", None)):
                        tool_call_detected = True
                        if hasattr(stream, "aclose"):
                            await stream.aclose()
                        break

                    token = (delta.content if delta else None) or ""
                    if token:
                        full_text += token
                        emitted_text += token
                        yield f"data: {json.dumps({'type': 'token', 'value': token})}\n\n"

        except asyncio.CancelledError:
            logger.info("Chat SSE stream cancelled; closing upstream model stream.")
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            raise
        except Exception as stream_err:
            logger.error("Mid-stream failure reading model chunks: %s", stream_err)
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
            yield f"data: {json.dumps({'type': 'error', 'detail': str(stream_err), 'terminal': True})}\n\n"
            return

        if tool_call_detected:
            result = await orchestrator.handle_message(
                conversation_id=req.conversation_id,
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "agent"
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
                async for chunk in stream_chunks(response_text):
                    if not is_first:
                        await asyncio.sleep(0.012)
                    is_first = False
                    yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"
            else:
                # Partial streamed text does NOT match orchestrator response —
                # send a replace event so the client discards the leaked markup
                # and replaces it with the clean tool-call response.
                yield f"data: {json.dumps({'type': 'replace', 'value': response_text})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        if not full_text.strip():
            result = await orchestrator.handle_message(
                conversation_id=req.conversation_id,
                message=message,
                user_id=user_id,
                guest_id=guest_id,
                history=history_items if history_items else None,
                memory_context=memory_context if memory_context else None,
                persist=False,
            )
            response_text = result.get("response", "")
            skill_used = result.get("skill_used") or "chat"
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            is_first = True
            async for chunk in stream_chunks(response_text):
                if not is_first:
                    await asyncio.sleep(0.012)
                is_first = False
                yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
            _schedule_stream_persistence(conv_id, message, response_text, user_id, guest_id, skill_used)
            return

        _schedule_stream_persistence(conv_id, message, full_text, user_id, guest_id, "chat")

        if usage_data:
            record_usage(_settings.ROUTER_MODEL, getattr(usage_data, "prompt_tokens", 30), getattr(usage_data, "completion_tokens", 15))
        else:
            prompt_est = len(message.split()) * 3
            completion_est = len(full_text.split())
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'})}\n\n"

    except asyncio.CancelledError:
        logger.info("Chat SSE stream cancelled by client disconnect.")
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        raise
    except Exception as e:
        logger.error("SSE stream outer error: %s", e)
        if stream and hasattr(stream, "aclose"):
            await stream.aclose()
        yield f"data: {json.dumps({'type': 'error', 'detail': str(e), 'terminal': True})}\n\n"
