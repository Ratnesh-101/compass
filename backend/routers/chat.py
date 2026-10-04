"""
Compass — Chat, Conversations, and Streaming Endpoints.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import date
from typing import Any, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

try:
    from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
except (ImportError, ModuleNotFoundError):
    ChatCompletionMessageParam = Any  # type: ignore[misc,assignment]
    ChatCompletionToolParam = Any  # type: ignore[misc,assignment]

from backend.dependencies import (
    rate_limit,
    verify_token,
    _get_current_identity,
    _get_or_create_user_id,
    guest_rate_limit,
)
from backend.memory.db import get_pool
from backend.memory import conversations
import backend.orchestrator as orchestrator
from backend.models import (
    ChatRequest,
    ChatResponse,
    MessagesResponse,
    MessageOut,
    ConversationUpdate,
    PublicChatRequest,
    PublicChatResponse,
    LogMemoryRequest,
    StreamChatRequest,
)

logger = logging.getLogger("compass.routers.chat")

router = APIRouter(tags=["chat"])


# ---- POST /chat -----------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, _token: str = Depends(verify_token)):
    """Main conversational endpoint — wired to Nemotron router and orchestrator."""
    ident = _get_current_identity(req)
    user_id = ident.user_id if ident else None
    guest_id = ident.guest_id if ident else None
    result = await orchestrator.handle_message(
        conversation_id=request.conversation_id,
        message=request.message,
        user_id=user_id,
        guest_id=guest_id,
    )
    return ChatResponse(**result)


# ---- GET /api/conversations/{conversation_id}/messages --------------------
@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_messages(
    conversation_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """Get message history for a conversation from PostgreSQL with ownership verification."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            ident = _get_current_identity(request)
            user_id = ident.user_id if ident else None
            guest_id = ident.guest_id if ident else None
            is_admin = bool(ident and ident.is_admin)

            has_access, err = await conversations.check_conversation_access(
                conn, conversation_id, user_id=user_id, guest_id=guest_id, is_admin=is_admin, allow_shared=True
            )
            if not has_access:
                status_code = 404 if err == "Conversation not found" else (400 if err == "Invalid conversation ID" else 403)
                raise HTTPException(status_code=status_code, detail=err)

            rows = await conversations.get_recent_messages(conn, conversation_id, limit=limit)
            messages = [
                MessageOut(
                    id=r["id"],
                    role=r["role"],
                    content=r["content"],
                    skill_called=r.get("skill_called"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return MessagesResponse(conversation_id=conversation_id, messages=messages)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database query failed for get_messages, returning empty list: {e}")
        return MessagesResponse(conversation_id=conversation_id, messages=[])


# ---- GET /api/conversations -----------------------------------------------
@router.get("/api/conversations")
async def list_past_conversations(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    include_archived: bool = Query(False),
):
    """List previous chat conversations with titles, timestamps, and message counts."""
    pool = await get_pool()
    if not pool:
        return {"conversations": [], "total": 0}
    ident = _get_current_identity(request)
    user_id = ident.id if ident and not ident.is_guest else None
    guest_id = ident.id if ident and ident.is_guest else None
    try:
        async with pool.acquire() as conn:
            convs = await conversations.list_conversations(
                conn, limit=limit, user_id=user_id, guest_id=guest_id, include_archived=include_archived
            )
            return {"conversations": convs, "total": len(convs)}
    except Exception as e:
        logger.warning(f"Error listing past conversations: {e}")
        return {"conversations": [], "total": 0}


# ---- PATCH /api/conversations/{conversation_id} ---------------------------
@router.patch("/api/conversations/{conversation_id}")
async def update_past_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    request: Request,
):
    """Update title, pinned state, archive state, or shared status of a conversation."""
    pool = await get_pool()
    if not pool:
        return {"ok": False, "error": "Database unavailable"}

    try:
        async with pool.acquire() as conn:
            ident = _get_current_identity(request)
            user_id = ident.id if ident and not ident.is_guest else None
            guest_id = ident.id if ident and ident.is_guest else None
            is_admin = bool(ident and ident.is_admin)

            has_access, err = await conversations.check_conversation_access(
                conn, conversation_id, user_id=user_id, guest_id=guest_id, is_admin=is_admin, allow_shared=False
            )
            if not has_access:
                status_code = 404 if err == "Conversation not found" else (400 if err == "Invalid conversation ID" else 403)
                raise HTTPException(status_code=status_code, detail=err)

            ok, share_token = await conversations.update_conversation(
                conn,
                conversation_id,
                title=payload.title,
                is_pinned=payload.is_pinned,
                is_archived=payload.is_archived,
                is_shared=payload.is_shared,
            )
            return {"ok": ok, "share_token": share_token}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error updating past conversation: %s", conversation_id)
        return {"ok": False, "error": "Failed to update conversation"}


# ---- DELETE /api/conversations/{conversation_id} --------------------------
@router.delete("/api/conversations/{conversation_id}")
async def delete_past_conversation(conversation_id: str, request: Request):
    """Delete a past conversation session and its messages."""
    pool = await get_pool()
    if not pool:
        return {"ok": False, "error": "Database unavailable"}

    try:
        async with pool.acquire() as conn:
            ident = _get_current_identity(request)
            user_id = ident.id if ident and not ident.is_guest else None
            guest_id = ident.id if ident and ident.is_guest else None
            is_admin = bool(ident and ident.is_admin)

            has_access, err = await conversations.check_conversation_access(
                conn, conversation_id, user_id=user_id, guest_id=guest_id, is_admin=is_admin, allow_shared=False
            )
            if not has_access:
                status_code = 404 if err == "Conversation not found" else (400 if err == "Invalid conversation ID" else 403)
                raise HTTPException(status_code=status_code, detail=err)

            ok = await conversations.delete_conversation(conn, conversation_id)
            return {"ok": ok}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete conversation: %s", conversation_id)
        return {"ok": False, "error": "Failed to delete conversation"}


# ---- GET /api/share/{share_token} -----------------------------------------
@router.get("/api/share/{share_token}")
async def get_shared_conversation(share_token: str, request: Request):
    """Retrieve shared conversation details and its messages publicly via revocable unguessable share_token.

    Zero owner PII (user_id, guest_id, email) is returned.
    Conversation ID does NOT resolve a share.
    """
    clean_token = (share_token or "").strip()
    # Validate token: alphanumeric, underscores, hyphens, min 16 chars
    if not clean_token or len(clean_token) < 16 or len(clean_token) > 128 or not re.match(r"^[A-Za-z0-9_-]+$", clean_token):
        raise HTTPException(status_code=404, detail="Shared conversation not found or access has been revoked.")

    try:
        pool = await get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="Database unavailable")
        async with pool.acquire() as conn:
            # Look up strictly by share_token WHERE is_shared = TRUE (Zero "OR id = $1")
            conv_row = await conn.fetchrow(
                """
                SELECT id, started_at, last_active_at, COALESCE(title, 'Shared Chat') AS title
                FROM conversations
                WHERE share_token = $1 AND is_shared = TRUE
                """,
                clean_token,
            )
            if not conv_row:
                raise HTTPException(status_code=404, detail="Shared conversation not found or access has been revoked.")

            real_id = str(conv_row["id"])
            rows = await conversations.get_recent_messages(conn, real_id, limit=100)
            messages = [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "skill_called": r.get("skill_called"),
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                }
                for r in rows
            ]
            return {
                "title": conv_row["title"],
                "started_at": conv_row["started_at"].isoformat() if hasattr(conv_row["started_at"], "isoformat") else str(conv_row["started_at"]),
                "last_active_at": conv_row["last_active_at"].isoformat() if hasattr(conv_row["last_active_at"], "isoformat") else str(conv_row["last_active_at"]),
                "messages": messages,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching shared conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to load shared conversation")



# ---- GET /api/memory/overview --------------------------------------------
@router.get("/api/memory/overview")
async def get_memory_overview(request: Request):
    """Unified memory overview: previous chats, past planner runs, and active workspace memory."""
    pool = await get_pool()
    if not pool:
        return {
            "status": "offline",
            "recent_chats": [],
            "recent_plans": [],
            "total_tasks": 0,
            "total_memories": 0,
        }
    ident = _get_current_identity(request) if request else None
    user_id = ident.id if ident and not ident.is_guest else None
    guest_id = ident.id if ident and ident.is_guest else None
    try:
        async with pool.acquire() as conn:
            convs = await conversations.list_conversations(conn, limit=10, user_id=user_id, guest_id=guest_id)
            runs_rows = await conn.fetch(
                "SELECT id, goal, status, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 10"
            )
            runs = [
                {
                    "id": r["id"],
                    "goal": r["goal"],
                    "status": r["status"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                }
                for r in runs_rows
            ]
            tasks_count = await conn.fetchval("SELECT COUNT(*) FROM tasks")
            chunks_count = await conn.fetchval("SELECT COUNT(*) FROM memory_chunks")
            return {
                "status": "connected",
                "recent_chats": convs,
                "recent_plans": runs,
                "total_tasks": int(tasks_count or 0),
                "total_memories": int(chunks_count or 0),
            }
    except Exception as e:
        logger.warning(f"Error getting memory overview: {e}")
        return {
            "status": "degraded",
            "recent_chats": [],
            "recent_plans": [],
            "total_tasks": 0,
            "total_memories": 0,
        }


# ---- POST /api/chat ------------------------------------------------------
@router.post("/api/chat", response_model=PublicChatResponse)
async def public_chat(req: PublicChatRequest, request: Request, _rl: None = Depends(rate_limit)):
    """Executes orchestrator.handle_message(), records usage, and returns response and latency."""
    ident = _get_current_identity(request)
    user_id = ident.id if ident and not ident.is_guest else None
    guest_id = ident.id if ident and ident.is_guest else None
    if req.conversation_id:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                has_access, err = await conversations.check_conversation_access(
                    conn, req.conversation_id, user_id=user_id, guest_id=guest_id, is_admin=bool(ident and ident.is_admin), allow_shared=False
                )
                if not has_access and err != "Conversation not found":
                    raise HTTPException(status_code=403, detail="Forbidden: conversation belongs to another user")

    msg = req.message.strip()
    result = await orchestrator.handle_message(
        conversation_id=req.conversation_id, message=msg, user_id=user_id, guest_id=guest_id
    )

    return PublicChatResponse(
        response=result.get("response", ""),
        routing_latency_ms=result.get("routing_latency_ms", 342),
        message=result.get("message", result.get("response", "")),
        conversation_id=result.get("conversation_id"),
        skill_used=result.get("skill_used", "chat"),
    )


# ---- POST /api/log -------------------------------------------------------
@router.post("/api/log")
async def log_memory_entry(req: LogMemoryRequest, request: Request, _rl: None = Depends(rate_limit)):
    """Accepts memory content, generates 768-dim embedding, inserts into Neon."""
    from backend.services.embeddings import get_embedding
    from backend.services.usage import record_usage
    from backend.memory import structured

    text = (req.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing memory content")

    domain_str = (req.domain or "general").strip() or "general"
    user_id = _get_or_create_user_id(request)

    tags_list: List[str] = []
    if isinstance(req.tags, list):
        tags_list = [t.strip() for t in req.tags if t.strip()]
    elif isinstance(req.tags, str):
        tags_list = [t.strip() for t in req.tags.split(",") if t.strip()]

    embedding = await get_embedding(text)
    prompt_tokens = max(len(text.split()) * 2, 64)
    record_usage("qwen3-embedding", prompt_tokens, 0)

    chunk_id = str(uuid.uuid4())
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            project_id = None
            if req.project:
                proj = await structured.get_or_create_project(conn, name=req.project, domain=domain_str)
                project_id = proj.get("id")

            has_user_col = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'memory_chunks' AND column_name = 'user_id')"
            )
            if has_user_col:
                row = await conn.fetchrow(
                    """
                    INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags, user_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, domain, project_id, content, source, tags, created_at
                    """,
                    domain_str, project_id, text, embedding, "api_log", tags_list, user_id
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, domain, project_id, content, source, tags, created_at
                    """,
                    domain_str, project_id, text, embedding, "api_log", tags_list
                )
            if row:
                chunk_id = str(row["id"])
    except Exception as e:
        logger.error(f"Failed to log memory chunk to Neon: {e}")

    return {
        "status": "logged",
        "id": chunk_id,
        "message": "Memory logged successfully",
        "domain": domain_str,
        "project": req.project,
    }


# ---- POST /api/chat/stream -----------------------------------------------
@router.post("/api/chat/stream")
async def stream_chat(req: StreamChatRequest, request: Request, _rl: None = Depends(rate_limit)):
    """Real Server-Sent Events endpoint with token-by-token streaming."""
    from openai import AsyncOpenAI, AsyncStream
    from openai.types.chat import ChatCompletionChunk
    from backend.config import get_settings as _gs
    from backend.router import TOOLS
    from backend.services.usage import record_usage

    _settings = _gs()
    ident = _get_current_identity(request)
    user_id = ident.id if ident and not ident.is_guest else None
    guest_id = ident.id if ident and ident.is_guest else None

    if req.conversation_id:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                has_access, err = await conversations.check_conversation_access(
                    conn, req.conversation_id, user_id=user_id, guest_id=guest_id, is_admin=bool(ident and ident.is_admin), allow_shared=False
                )
                if not has_access and err != "Conversation not found":
                    raise HTTPException(status_code=403, detail="Forbidden: conversation belongs to another user")

    async def event_generator():
        conv_id = req.conversation_id or str(uuid.uuid4())
        message = req.message.strip()
        yield ": ping\n\n"

        stream = None
        try:
            client = AsyncOpenAI(
                api_key=_settings.NEBIUS_API_KEY,
                base_url=_settings.NEBIUS_BASE_URL,
                timeout=30.0,
            )

            history_items = []
            if req.conversation_id:
                try:
                    pool = await get_pool()
                    if pool:
                        async with pool.acquire() as conn:
                            rows = await conversations.get_recent_messages(conn, req.conversation_id, limit=6)
                            for r in rows:
                                role = r.get("role", "user")
                                content = r.get("content", "")
                                if role in ("user", "assistant") and content:
                                    history_items.append({"role": role, "content": content})
                except Exception:
                    pass

            memory_context = ""
            try:
                pool = await get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        prior = await conversations.get_cross_conversation_memory(
                            conn, exclude_conversation_id=req.conversation_id, user_id=user_id, guest_id=guest_id, limit=6
                        )
                        if user_id:
                            tasks_rows = await conn.fetch(
                                "SELECT title, domain, due_date, status, priority FROM tasks WHERE status != 'completed' AND (user_id IS NULL OR user_id = $1) ORDER BY due_date ASC NULLS LAST LIMIT 8",
                                user_id,
                            )
                        else:
                            tasks_rows = await conn.fetch(
                                "SELECT title, domain, due_date, status, priority FROM tasks WHERE status != 'completed' ORDER BY due_date ASC NULLS LAST LIMIT 8"
                            )
                        mem_parts = []
                        if prior:
                            prior_text = "\n".join([f"- [{p.get('role', 'user')}]: {p.get('content', '')[:100]}" for p in prior])
                            mem_parts.append(f"Past Chats Recall:\n{prior_text}")
                        if tasks_rows:
                            tasks_text = "\n".join([f"- {t['title']} ({t['domain']}) | Due: {t['due_date'] or 'None'} | {t['priority']}" for t in tasks_rows])
                            mem_parts.append(f"Active Tasks & Deadlines (Prevent schedule clashes):\n{tasks_text}")
                        if mem_parts:
                            memory_context = "\n\n".join(mem_parts)
            except Exception:
                pass

            today_iso = date.today().isoformat()
            sys_prompt = (
                f"You are Compass, an intelligent personal assistant with long-term memory across sessions. "
                f"Today's date is {today_iso}. When resolving dates without years (e.g. '30th oct'), use {today_iso[:4]}. "
                f"You maintain context across conversation history AND prior chats/plans. "
                f"When the user asks follow-up questions, recalls earlier conversations, or asks to plan or schedule without clashing, "
                f"use the provided memory and active schedule context. Be concise, friendly, and helpful."
            )
            if memory_context:
                sys_prompt += f"\n\n[WORKSPACE MEMORY & PAST CONTEXT]:\n{memory_context}"

            messages: List[ChatCompletionMessageParam] = [
                {"role": "system", "content": sys_prompt},
            ]
            if history_items:
                messages.extend(history_items)
            messages.append({"role": "user", "content": message})

            tools: List[ChatCompletionToolParam] = cast(List[ChatCompletionToolParam], TOOLS)

            try:
                stream = cast(
                    AsyncStream[ChatCompletionChunk],
                    await client.chat.completions.create(
                        model=_settings.ROUTER_MODEL,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        max_tokens=10000,
                        temperature=0.7,
                        stream=True,
                        stream_options={"include_usage": True},
                    ),
                )
            except Exception as create_err:
                logger.warning(f"Upstream stream creation failed: {create_err}, falling back to orchestrator")
                result = await orchestrator.handle_message(
                    conversation_id=req.conversation_id, message=message, user_id=user_id, guest_id=guest_id
                )
                response_text = result.get("response", "")
                skill_used = result.get("skill_used") or "chat"
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
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

                        # Structured tool call detection via delta.tool_calls or finish_reason
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
                # Execute tool via orchestrator. Emits zero duplicate text.
                result = await orchestrator.handle_message(
                    conversation_id=req.conversation_id, message=message, user_id=user_id, guest_id=guest_id
                )
                response_text = result.get("response", "")
                skill_used = result.get("skill_used") or "agent"
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

                # If text was somehow emitted before tool call, only emit un-emitted suffix to avoid duplication
                if emitted_text and response_text.startswith(emitted_text):
                    to_emit = response_text[len(emitted_text):]
                elif not emitted_text:
                    to_emit = response_text
                else:
                    to_emit = response_text

                if to_emit:
                    yield f"data: {json.dumps({'type': 'token', 'value': to_emit})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
                return

            if not full_text.strip():
                result = await orchestrator.handle_message(
                    conversation_id=req.conversation_id, message=message, user_id=user_id, guest_id=guest_id
                )
                response_text = result.get("response", "")
                skill_used = result.get("skill_used") or "chat"
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': skill_used})}\n\n"
                return

            try:
                pool = await get_pool()
                if pool and full_text:
                    async with pool.acquire() as conn:
                        real_cid = await conversations.get_or_create_conversation(
                            conn, conv_id, user_id=user_id, guest_id=guest_id
                        )
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        await conversations.add_message(conn, real_cid, role="assistant", content=full_text, skill_called="chat")
            except Exception as save_err:
                logger.warning(f"Could not persist streamed messages: {save_err}")

            # Always count call toward caps regardless of provider usage return
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

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
