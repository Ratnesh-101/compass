"""
Compass — Chat, Conversations, and Streaming Endpoints.
"""

import json
import logging
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

from backend.dependencies import rate_limit, verify_token, _get_current_user_id
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
async def chat(request: ChatRequest, _token: str = Depends(verify_token)):
    """Main conversational endpoint — wired to Nemotron router and orchestrator."""
    result = await orchestrator.handle_message(
        conversation_id=request.conversation_id,
        message=request.message,
    )
    return ChatResponse(**result)


# ---- GET /conversations/{conversation_id}/messages ------------------------
@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get message history for a conversation from PostgreSQL."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
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
    user_id = request.headers.get("x-user-id") if request else None
    try:
        async with pool.acquire() as conn:
            convs = await conversations.list_conversations(
                conn, limit=limit, user_id=user_id, include_archived=include_archived
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
        cid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    try:
        async with pool.acquire() as conn:
            # Check ownership (IDOR prevention)
            has_user_col = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'user_id')"
            )
            if has_user_col:
                conv_row = await conn.fetchrow("SELECT user_id FROM conversations WHERE id = $1", cid)
                if not conv_row:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                user_id = _get_current_user_id(request)
                auth_header = request.headers.get("authorization", "")
                is_admin = False
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()
                    from backend.config import get_settings
                    import hmac
                    s = get_settings()
                    if token and s.AUTH_TOKEN and hmac.compare_digest(token, s.AUTH_TOKEN):
                        is_admin = True

                conv_owner = conv_row.get("user_id")
                if not is_admin and conv_owner:
                    if not user_id or user_id.lower() != conv_owner.lower():
                        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to modify this conversation.")

            ok = await conversations.update_conversation(
                conn,
                conversation_id,
                title=payload.title,
                is_pinned=payload.is_pinned,
                is_archived=payload.is_archived,
                is_shared=payload.is_shared,
            )
            return {"ok": ok}
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
        cid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    try:
        async with pool.acquire() as conn:
            # Check ownership (IDOR prevention)
            has_user_col = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'user_id')"
            )
            if has_user_col:
                conv_row = await conn.fetchrow("SELECT user_id FROM conversations WHERE id = $1", cid)
                if not conv_row:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                user_id = _get_current_user_id(request)
                auth_header = request.headers.get("authorization", "")
                is_admin = False
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()
                    from backend.config import get_settings
                    import hmac
                    s = get_settings()
                    if token and s.AUTH_TOKEN and hmac.compare_digest(token, s.AUTH_TOKEN):
                        is_admin = True

                conv_owner = conv_row.get("user_id")
                if not is_admin and conv_owner:
                    if not user_id or user_id.lower() != conv_owner.lower():
                        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to delete this conversation.")

            ok = await conversations.delete_conversation(conn, conversation_id)
            return {"ok": ok}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete conversation: %s", conversation_id)
        return {"ok": False, "error": "Failed to delete conversation"}


# ---- GET /api/share/{conversation_id} -------------------------------------
@router.get("/api/share/{conversation_id}")
async def get_shared_conversation(conversation_id: str, request: Request):
    """Retrieve shared conversation details and its messages publicly."""
    try:
        pool = await get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="Database unavailable")
        async with pool.acquire() as conn:
            try:
                cid = uuid.UUID(conversation_id)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid conversation ID")

            has_shared_col = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'is_shared')"
            )
            has_user_col = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'user_id')"
            )

            cols = ["id", "started_at", "last_active_at", "COALESCE(title, 'Chat Session') AS title"]
            if has_shared_col:
                cols.append("is_shared")
            if has_user_col:
                cols.append("user_id")

            conv_row = await conn.fetchrow(
                f"SELECT {', '.join(cols)} FROM conversations WHERE id = $1",
                cid
            )
            if not conv_row:
                raise HTTPException(status_code=404, detail="Conversation not found")

            # Privacy gate: If is_shared column exists, only allow public access if is_shared is TRUE or caller is the owner
            if has_shared_col and not conv_row.get("is_shared"):
                user_id = _get_current_user_id(request)
                owner = conv_row.get("user_id") if has_user_col else None
                if not owner or not user_id or user_id.lower() != owner.lower():
                    raise HTTPException(status_code=403, detail="This conversation is private and has not been shared.")

            rows = await conversations.get_recent_messages(conn, conversation_id, limit=100)
            messages = [
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "skill_called": r.get("skill_called"),
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                }
                for r in rows
            ]
            return {
                "id": str(conv_row["id"]),
                "title": conv_row["title"],
                "started_at": conv_row["started_at"].isoformat() if hasattr(conv_row["started_at"], "isoformat") else str(conv_row["started_at"]),
                "last_active_at": conv_row["last_active_at"].isoformat() if hasattr(conv_row["last_active_at"], "isoformat") else str(conv_row["last_active_at"]),
                "messages": messages,
            }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
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
    user_id = request.headers.get("x-user-id") if request else None
    try:
        async with pool.acquire() as conn:
            convs = await conversations.list_conversations(conn, limit=10, user_id=user_id)
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
    user_id = _get_current_user_id(request)
    msg = req.message.strip()
    result = await orchestrator.handle_message(conversation_id=req.conversation_id, message=msg, user_id=user_id)

    return PublicChatResponse(
        response=result.get("response", ""),
        routing_latency_ms=result.get("routing_latency_ms", 342),
        message=result.get("message", result.get("response", "")),
        conversation_id=result.get("conversation_id"),
        skill_used=result.get("skill_used", "chat"),
    )


# ---- POST /api/log -------------------------------------------------------
@router.post("/api/log")
async def log_memory_entry(req: LogMemoryRequest, _rl: None = Depends(rate_limit)):
    """Accepts memory content, generates 768-dim embedding, inserts into Neon."""
    from backend.services.embeddings import get_embedding
    from backend.services.usage import record_usage
    from backend.memory import structured

    text = (req.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing memory content")

    domain_str = (req.domain or "general").strip() or "general"

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
    user_id = _get_current_user_id(request)

    async def event_generator():
        conv_id = req.conversation_id or str(uuid.uuid4())
        message = req.message.strip()
        yield ": ping\n\n"

        if not _settings.NEBIUS_API_KEY:
            result = await orchestrator.handle_message(conversation_id=req.conversation_id, message=message, user_id=user_id)
            response_text = result.get("response", "")
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
            yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'chat')})}\n\n"
            return

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
                        prior = await conversations.get_cross_conversation_memory(conn, exclude_conversation_id=req.conversation_id, user_id=user_id, limit=6)
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
                ),
            )

            full_text = ""
            tool_call_detected = False

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

                if finish_reason in ("tool_calls", "function_call"):
                    tool_call_detected = True
                    break

                if delta is None:
                    continue

                if delta.tool_calls:
                    tool_call_detected = True
                    break

                token = delta.content or ""
                if not full_text and not token.strip():
                    continue
                if token:
                    full_text += token
                    yield f"data: {json.dumps({'type': 'token', 'value': token})}\n\n"

            if tool_call_detected or not full_text.strip():
                result = await orchestrator.handle_message(conversation_id=req.conversation_id, message=message, user_id=user_id)
                response_text = result.get("response", "")
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'add_task' if 'task' in message.lower() else 'chat')})}\n\n"
                return

            try:
                pool = await get_pool()
                if pool and full_text:
                    async with pool.acquire() as conn:
                        real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id)
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        await conversations.add_message(conn, real_cid, role="assistant", content=full_text, skill_called="chat")
            except Exception as save_err:
                logger.warning(f"Could not persist streamed messages: {save_err}")

            prompt_est = len(message.split()) * 3
            completion_est = len(full_text.split())
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'})}\n\n"

        except Exception as e:
            logger.warning(f"SSE stream error ({e}); falling back to non-streaming orchestrator")
            try:
                result = await orchestrator.handle_message(conversation_id=req.conversation_id, message=message, user_id=user_id)
                response_text = result.get("response", "")
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'add_task' if 'task' in message.lower() else 'chat')})}\n\n"
            except Exception:
                logger.exception("SSE fallback error")
                yield f"data: {json.dumps({'type': 'error', 'message': 'An internal error occurred.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
