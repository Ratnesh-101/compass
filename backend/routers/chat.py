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
        tone=request.tone,
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
                conn, conversation_id, user_id=user_id, guest_id=guest_id, is_admin=is_admin, allow_shared=False
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

            ok, _ = await conversations.update_conversation(
                conn,
                conversation_id,
                title=payload.title,
                is_pinned=payload.is_pinned,
                is_archived=payload.is_archived,
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
    from backend.services.chat_stream import generate_chat_events

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

    return StreamingResponse(
        generate_chat_events(req, request, user_id=user_id, guest_id=guest_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

