"""
Compass — Anonymous Guest Identity and Migration Endpoints.

Handles guest session generation, status checking, selective & bulk conversation
and memory migration from guest identity to authenticated user account.
"""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.config import get_settings
from backend.dependencies import (
    _get_current_identity,
    generate_guest_token,
    verify_guest_token,
    guest_rate_limit,
)
from backend.memory.db import get_pool
from backend.memory import conversations

logger = logging.getLogger("compass.routers.migration")
settings = get_settings()

router = APIRouter(tags=["migration"])


# ---------------------------------------------------------------------------
# Request & Response Models
# ---------------------------------------------------------------------------
class ImportSelectedBody(BaseModel):
    conversation_ids: List[str] = Field(..., description="List of guest conversation UUIDs to import")
    import_memory: bool = Field(True, description="Whether to also copy guest workspace memories")


# ---------------------------------------------------------------------------
# Guest Session Initialization & Recovery
# ---------------------------------------------------------------------------
@router.api_route("/api/guest/session", methods=["GET", "POST"])
async def guest_session_endpoint(request: Request, response: Response):
    """Obtain or restore an anonymous guest session.

    - POST: Generates a fresh, cryptographically random UUID guest identity and an HMAC-signed token,
            persisting it in a secure cookie. Throttled by mint_rate_limit.
    - GET: Validates and recovers an existing active guest session without constructing cookies from user input.
    """
    if request.method == "GET":
        hdr_token = request.headers.get("x-guest-token")
        cookie_token = request.cookies.get("compass_guest_token")
        raw_token = hdr_token or cookie_token

        if not raw_token:
            raise HTTPException(status_code=401, detail="No active guest session found.")

        verified_gid = verify_guest_token(raw_token)
        if not verified_gid:
            raise HTTPException(status_code=401, detail="Invalid or expired guest session token.")

        return {
            "status": "ok",
            "guest_id": verified_gid,
            "guest_token": raw_token,
            "is_new": False,
        }

    # POST: Enforce strict guest-mint rate limit per IP and global daily cap
    from backend.dependencies import mint_rate_limit
    await mint_rate_limit(request)

    from backend.services.budgets import check_global_mint_cap, record_guest_mint
    await check_global_mint_cap()

    # Always generate a brand new cryptographically random guest identity (zero user input)
    gid, token = generate_guest_token()
    from backend.services.security import get_client_ip
    await record_guest_mint(gid, get_client_ip(request))

    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or settings.is_production()
    )

    response.set_cookie(
        key="compass_guest_token",
        value=token,
        max_age=86400 * int(getattr(settings, "GUEST_RETENTION_DAYS", 30)),
        httponly=False,  # Allow client JS to read or supply in X-Guest-Token header
        secure=is_https,
        samesite="lax",
        path="/",
    )

    return {
        "status": "ok",
        "guest_id": gid,
        "guest_token": token,
        "is_new": True,
    }


# ---------------------------------------------------------------------------
# Migration Status Check
# ---------------------------------------------------------------------------
@router.get("/api/migration/status")
async def get_migration_status(request: Request):
    """Check if the active guest session has conversations or memories eligible for migration.

    Must be called by an authenticated user who has an active guest session.
    """
    ident = _get_current_identity(request)
    user_id = ident.user_id if ident else None
    guest_id = ident.guest_id if ident else None

    if not user_id:
        return {
            "eligible": False,
            "reason": "unauthenticated",
            "message": "User is not signed in.",
            "total_conversations": 0,
            "unimported_conversations": 0,
            "total_memories": 0,
        }

    if not guest_id:
        return {
            "eligible": False,
            "reason": "no_guest_session",
            "message": "No active guest identity found in request.",
            "total_conversations": 0,
            "unimported_conversations": 0,
            "total_memories": 0,
        }

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        overview = await conversations.get_guest_migration_overview(conn, guest_id, user_id)
        return overview


# ---------------------------------------------------------------------------
# List Guest Conversations Available for Import
# ---------------------------------------------------------------------------
@router.get("/api/migration/conversations")
async def list_migration_conversations(request: Request):
    """List all conversations owned by the current guest identity, along with import status."""
    ident = _get_current_identity(request)
    user_id = ident.user_id if ident else None
    guest_id = ident.guest_id if ident else None

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to view migration candidates.")
    if not guest_id:
        return {"guest_id": None, "conversations": [], "total": 0}

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        items = await conversations.list_guest_conversations_for_migration(conn, guest_id, user_id)
        return {
            "guest_id": guest_id,
            "user_id": user_id,
            "conversations": items,
            "total": len(items),
        }


# ---------------------------------------------------------------------------
# Import All Guest Data (with /api/guest/migrate alias)
# ---------------------------------------------------------------------------
@router.post("/api/migration/import-all")
@router.post("/api/guest/migrate")
async def import_all_guest_data(request: Request, _rl: None = Depends(guest_rate_limit)):
    """Import all unimported guest conversations and memories into the authenticated user account.

    Strictly preserves the original guest data and avoids duplicates.
    """
    ident = _get_current_identity(request)
    user_id = ident.user_id if ident else None
    guest_id = ident.guest_id if ident else None

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to import guest data.")
    if not guest_id:
        raise HTTPException(status_code=400, detail="No active guest session found to import from.")

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        imported_convs = await conversations.migrate_all_guest_conversations(conn, guest_id, user_id)
        imported_mems = await conversations.migrate_guest_memories(conn, guest_id, user_id)

    logger.info(
        "Migrated all guest data: guest=%s -> user=%s (convs=%d, mems=%d)",
        guest_id, user_id, imported_convs, imported_mems
    )

    return {
        "status": "ok",
        "imported_count": imported_convs,
        "imported_conversations": imported_convs,
        "imported_memories": imported_mems,
        "message": f"Successfully imported {imported_convs} conversation(s) and {imported_mems} memory item(s).",
    }


# ---------------------------------------------------------------------------
# Selectively Import Specific Conversations
# ---------------------------------------------------------------------------
@router.post("/api/migration/import-selected")
async def import_selected_guest_data(body: ImportSelectedBody, request: Request, _rl: None = Depends(guest_rate_limit)):
    """Selectively import designated guest conversations into the authenticated user account.

    Idempotent: conversations already imported will not be duplicated.
    Original guest records remain intact.
    """
    ident = _get_current_identity(request)
    user_id = ident.user_id if ident else None
    guest_id = ident.guest_id if ident else None

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to import guest data.")
    if not guest_id:
        raise HTTPException(status_code=400, detail="No active guest session found to import from.")

    if not body.conversation_ids:
        return {"status": "ok", "imported_conversations": 0, "imported_memories": 0, "message": "No conversations selected."}

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    imported_convs = 0
    already_imported_count = 0
    details = []
    import uuid as _uuid
    async with pool.acquire() as conn:
        for cid_str in body.conversation_ids:
            try:
                cid = _uuid.UUID(str(cid_str))
                existing = await conn.fetchval(
                    "SELECT user_conversation_id FROM guest_migration_log WHERE guest_conversation_id = $1 AND user_id = $2",
                    cid, user_id
                )
                if existing:
                    already_imported_count += 1
                    details.append({"id": cid_str, "status": "already_imported", "already_imported": True})
                    continue
            except Exception as e:
                logger.debug("Failed querying guest_migration_log table: %s", e)

            res = await conversations.migrate_single_conversation(conn, cid_str, guest_id, user_id)
            if res:
                imported_convs += 1
                details.append({"id": cid_str, "status": "imported", "already_imported": False})

        imported_mems = 0
        if body.import_memory:
            imported_mems = await conversations.migrate_guest_memories(conn, guest_id, user_id)

    return {
        "status": "ok",
        "imported_count": imported_convs,
        "imported_conversations": imported_convs,
        "already_imported_count": already_imported_count,
        "imported_memories": imported_mems,
        "conversations": details,
        "message": f"Imported {imported_convs} conversation(s) and {imported_mems} memory item(s).",
    }


# ---------------------------------------------------------------------------
# Skip Migration for Now
# ---------------------------------------------------------------------------
@router.post("/api/migration/skip")
async def skip_migration(response: Response):
    """Acknowledge dismissal of the migration modal for the current session."""
    # Sets a lightweight session cookie to prevent annoying the user on subsequent immediate requests
    response.set_cookie(
        key="compass_migration_skipped",
        value="1",
        max_age=86400 * 7,
        httponly=False,
        samesite="lax",
    )
    return {"status": "ok", "message": "Migration dismissed for now. Guest conversations remain preserved."}


# ---------------------------------------------------------------------------
# Privacy / Data Controls — Delete Guest Data
# ---------------------------------------------------------------------------
@router.delete("/api/guest/data")
async def delete_guest_data_endpoint(request: Request, response: Response):
    """Permanently delete all guest conversations and memories associated with the verified guest token."""
    ident = _get_current_identity(request)
    guest_id = ident.guest_id if ident else None
    if not guest_id:
        raise HTTPException(status_code=400, detail="No valid guest identity token provided.")

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        result = await conversations.delete_guest_data(conn, guest_id)

    response.delete_cookie("compass_guest_token")
    return {
        "status": "ok",
        "deleted_conversations": result["deleted_conversations"],
        "deleted_memories": result["deleted_memories"],
        "message": "All guest conversations and memories have been permanently deleted.",
    }
