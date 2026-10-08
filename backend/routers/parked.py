"""
Compass — Parked Thoughts API Router ("Park it" shelf).

Endpoints for inspecting and resolving thoughts and tangents parked on the shelf.
"""

from typing import Any, Dict, Optional
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.dependencies import _get_current_identity
from backend.memory.db import get_pool
from backend.memory.parked import (
    MAX_PARKED_TEXT_LENGTH,
    list_parked_thoughts,
    park_thought,
    resolve_parked_thought,
    sanitize_parked_text,
)

logger = logging.getLogger("compass.routers.parked")

router = APIRouter(prefix="/api/parked", tags=["parked"])


class ParkThoughtRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None


@router.get("")
async def get_parked_thoughts(
    request: Request,
) -> Dict[str, Any]:
    """Retrieve all open thoughts on the parked shelf for the authenticated user."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ident = _get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Unauthorized")
    owner_id = ident.id

    async with pool.acquire() as conn:
        thoughts = await list_parked_thoughts(conn, user_id=owner_id, status="parked")

    return {"user_id": owner_id, "parked": thoughts}


@router.post("")
async def create_parked_thought(
    body: ParkThoughtRequest,
    request: Request,
) -> Dict[str, Any]:
    """Add a thought or tangent to the parked shelf."""
    if len(body.text) > 500:
        raise HTTPException(status_code=400, detail="Thought text exceeds maximum length (500 characters)")

    clean_text = sanitize_parked_text(body.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Thought text cannot be empty")

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ident = _get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Unauthorized")
    owner_id = ident.id

    async with pool.acquire() as conn:
        record = await park_thought(
            conn,
            text=clean_text,
            user_id=owner_id,
            conversation_id=body.conversation_id,
        )

    return {"success": True, "thought": record}


@router.patch("/{thought_id}")
@router.patch("/{thought_id}/resolve")
async def mark_parked_done(
    thought_id: int,
    request: Request,
) -> Dict[str, Any]:
    """Mark a parked thought as done / resolved."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ident = _get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Unauthorized")
    owner_id = ident.id

    async with pool.acquire() as conn:
        resolved = await resolve_parked_thought(conn, thought_id=thought_id, user_id=owner_id)

    if not resolved:
        raise HTTPException(status_code=404, detail=f"Parked thought #{thought_id} not found")

    return {"success": True, "thought_id": thought_id, "status": "done"}

