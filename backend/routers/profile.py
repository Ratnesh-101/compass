"""
Compass — Profile Facts API Router.

Endpoints for inspecting and managing persistent user profile facts (name, goals, preferences).
"""

from typing import Any, Dict
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from backend.dependencies import _get_current_identity, _get_or_create_user_id, verify_token
from backend.memory.db import get_pool
from backend.memory.profile import get_profile_facts, delete_profile_fact

logger = logging.getLogger("compass.routers.profile")

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/facts")
async def get_facts(
    request: Request,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Retrieve all stored profile facts for the authenticated user."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ident = _get_current_identity(request)
    user_id = (ident.user_id or ident.id) if ident else _get_or_create_user_id(request)

    async with pool.acquire() as conn:
        facts = await get_profile_facts(conn, user_id=user_id)

    return {"user_id": user_id, "facts": facts}


@router.delete("/facts/{key}")
async def delete_fact(
    key: str,
    request: Request,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Remove a stored profile fact by key."""

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ident = _get_current_identity(request)
    user_id = (ident.user_id or ident.id) if ident else _get_or_create_user_id(request)

    async with pool.acquire() as conn:
        removed = await delete_profile_fact(conn, key=key, user_id=user_id)

    if not removed:
        raise HTTPException(status_code=404, detail=f"Fact with key '{key}' not found")

    return {"success": True, "deleted_key": key}

