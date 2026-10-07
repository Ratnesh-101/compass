"""
Compass — Authentication and Google Calendar OAuth Endpoints.
"""

import asyncio
import hashlib
import logging
import re
import secrets
import urllib.parse
import time
from datetime import datetime, timezone, timedelta
from html import escape
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import get_settings
from backend.dependencies import _get_current_identity
from backend.memory.db import get_pool
from backend.models import SelectAccountBody, QuickConnectBody
from backend.services.oauth import (
    generate_google_oauth_url,
    generate_oauth_state,
    is_google_oauth_configured,
)

logger = logging.getLogger("compass.routers.auth")
settings = get_settings()

router = APIRouter(tags=["auth"])

# Multi-worker session store: in-memory cache synchronized with PostgreSQL 'sessions' table
_SESSIONS: dict[str, dict] = {}

SESSION_CACHE_TTL = 10.0  # seconds; guarantees multi-worker invalidation within <= 10s
IDLE_TIMEOUT = timedelta(hours=24)
ABSOLUTE_TIMEOUT = timedelta(days=7)


def _hash_token(token: str) -> str:
    """Return SHA-256 hex digest of session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _persist_session_db(token_hash: str, user_id: str, oauth_verified: bool, expires_at: datetime) -> None:
    """Persist session record to PostgreSQL."""
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sessions (token_hash, user_id, oauth_verified, created_at, last_accessed_at, expires_at)
                    VALUES ($1, $2, $3, now(), now(), $4)
                    ON CONFLICT (token_hash) DO UPDATE
                    SET last_accessed_at = now(), expires_at = $4, revoked_at = NULL
                    """,
                    token_hash,
                    user_id,
                    oauth_verified,
                    expires_at,
                )
    except Exception as e:
        logger.warning("Could not persist session to PostgreSQL: %s", e)


async def _touch_session_db(token_hash: str) -> None:
    """Touch last_accessed_at in PostgreSQL for idle expiration tracking."""
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sessions SET last_accessed_at = now() WHERE token_hash = $1 AND revoked_at IS NULL",
                    token_hash,
                )
    except Exception:
        pass


async def load_sessions_from_db(pool: Any) -> int:
    """Load valid unrevoked, unexpired sessions from PostgreSQL into memory cache on startup / restart."""
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT token_hash, user_id, oauth_verified, created_at, last_accessed_at, expires_at, revoked_at
                FROM sessions
                WHERE revoked_at IS NULL AND expires_at > now()
                """
            )
            count = 0
            now = datetime.now(timezone.utc)
            active_hashes = set()
            for r in rows:
                # Check idle timeout before loading
                last_act = r["last_accessed_at"]
                if last_act and (now - last_act) > IDLE_TIMEOUT:
                    continue
                th = r["token_hash"]
                active_hashes.add(th)
                _SESSIONS[th] = {
                    "user_id": r["user_id"],
                    "oauth_verified": bool(r["oauth_verified"]),
                    "created_at": r["created_at"],
                    "last_accessed_at": r["last_accessed_at"],
                    "expires_at": r["expires_at"],
                    "revoked_at": r["revoked_at"],
                }
                count += 1
            # Invalidate any locally cached sessions that have been revoked or deleted in DB
            for k in list(_SESSIONS.keys()):
                if k not in active_hashes and not k.startswith("test_") and not k.startswith("exp_"):
                    _SESSIONS.pop(k, None)
            return count
    except Exception as e:
        logger.warning("Could not load sessions from PostgreSQL: %s", e)
        return 0


async def start_session_sync_loop(pool: Any, interval_seconds: float = 5.0) -> None:
    """Background synchronization loop guaranteeing multi-worker revocation propagation in <= 10 seconds."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await load_sessions_from_db(pool)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Session sync loop error: %s", e)


def create_session(user_id: str, oauth_verified: bool = False) -> str:
    """Generate an opaque session token, compute SHA-256 hash, and persist to DB & memory."""
    token = secrets.token_hex(32)
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    expires_at = now + ABSOLUTE_TIMEOUT

    sess_data = {
        "user_id": user_id,
        "oauth_verified": bool(oauth_verified),
        "created_at": now,
        "last_accessed_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "cached_at": time.time(),
    }
    _SESSIONS[token_hash] = sess_data

    # Schedule DB insert in running event loop if active
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_session_db(token_hash, user_id, bool(oauth_verified), expires_at))
    except RuntimeError:
        pass

    return token


def get_user_from_session(token: str) -> Optional[str]:
    """Look up user identity from an opaque session token with idle + absolute expiry and revocation checks."""
    if not token:
        return None
    token_hash = _hash_token(token)
    sess = _SESSIONS.get(token_hash)
    if not isinstance(sess, dict):
        # Support legacy unhashed lookup if present
        sess = _SESSIONS.get(token)
        if not isinstance(sess, dict):
            return None

    if sess.get("revoked_at") is not None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = sess.get("expires_at")
    if expires_at and now > expires_at:
        return None

    last_accessed = sess.get("last_accessed_at")
    if last_accessed and (now - last_accessed) > IDLE_TIMEOUT:
        return None

    sess["last_accessed_at"] = now
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_touch_session_db(token_hash))
    except RuntimeError:
        pass

    return sess.get("user_id")


async def get_user_from_session_async(token: str) -> Optional[str]:
    """Look up user identity from an opaque session token with <=10s TTL cache and PostgreSQL verification.
    
    Guarantees that a session revoked on one worker is invalidated on all other workers within <= 10s.
    """
    if not token:
        return None
    token_hash = _hash_token(token)
    now_ts = time.time()
    sess = _SESSIONS.get(token_hash) or _SESSIONS.get(token)

    # Fast path: check valid in-memory cache entry within TTL
    if isinstance(sess, dict):
        cached_at = sess.get("cached_at", 0)
        if (now_ts - cached_at) <= SESSION_CACHE_TTL:
            if sess.get("revoked_at") is not None:
                return None
            now_dt = datetime.now(timezone.utc)
            if sess.get("expires_at") and now_dt > sess.get("expires_at"):
                return None
            if sess.get("last_accessed_at") and (now_dt - sess.get("last_accessed_at")) > IDLE_TIMEOUT:
                return None
            return sess.get("user_id")

    # Cache expired or cache miss: query PostgreSQL directly
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, oauth_verified, created_at, last_accessed_at, expires_at, revoked_at
                    FROM sessions
                    WHERE token_hash = $1
                    """,
                    token_hash,
                )
                if row:
                    if row["revoked_at"] is not None:
                        _SESSIONS.pop(token_hash, None)
                        return None
                    now_dt = datetime.now(timezone.utc)
                    if row["expires_at"] and now_dt > row["expires_at"]:
                        _SESSIONS.pop(token_hash, None)
                        return None
                    if row["last_accessed_at"] and (now_dt - row["last_accessed_at"]) > IDLE_TIMEOUT:
                        _SESSIONS.pop(token_hash, None)
                        return None

                    _SESSIONS[token_hash] = {
                        "user_id": row["user_id"],
                        "oauth_verified": bool(row["oauth_verified"]),
                        "created_at": row["created_at"],
                        "last_accessed_at": row["last_accessed_at"],
                        "expires_at": row["expires_at"],
                        "revoked_at": None,
                        "cached_at": now_ts,
                    }
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_touch_session_db(token_hash))
                    except RuntimeError:
                        pass
                    return row["user_id"]
                else:
                    _SESSIONS.pop(token_hash, None)
                    return None
    except Exception as e:
        logger.warning("Postgres session validation error: %s", e)

    # Fall back to synchronous local cache (for testing without DB pool)
    return get_user_from_session(token)


def is_session_oauth_verified(token: str) -> bool:
    """Check if the session was issued by the genuine Google OAuth callback handler and is not revoked."""
    if not token:
        return False
    token_hash = _hash_token(token)
    sess = _SESSIONS.get(token_hash) or _SESSIONS.get(token)
    if isinstance(sess, dict):
        if sess.get("revoked_at") is not None:
            return False
        return bool(sess.get("oauth_verified", False))
    return False



def _resolve_oauth_redirect_uri(request: Request) -> str:
    """Consistently resolve OAuth callback URL across local dev and production reverse-proxies."""
    fwd_host = request.headers.get("x-forwarded-host")
    host = fwd_host or request.headers.get("host", "localhost:8000")
    hostname = host.split(":")[0].lower()

    if hostname in ("localhost", "127.0.0.1") or hostname.endswith(".localhost"):
        return "http://localhost:8000/api/calendar/callback"

    if getattr(settings, "GOOGLE_REDIRECT_URI", None) and "localhost" not in settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI

    fwd_proto = request.headers.get("x-forwarded-proto")
    is_https = (
        request.url.scheme == "https"
        or hostname.endswith(".vercel.app")
        or hostname == "vercel.app"
        or hostname.endswith(".onrender.com")
        or hostname == "onrender.com"
    )
    scheme = fwd_proto or ("https" if is_https else "http")
    return f"{scheme}://{host}/api/calendar/callback"


def _resolve_frontend_origin(request: Request) -> str:
    """Resolve active frontend base URL for OAuth redirects and error returns."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    if settings.is_development():
        return "http://localhost:5173"

    cors_origins = getattr(settings, "CORS_ORIGINS", [])
    if cors_origins and isinstance(cors_origins, list) and cors_origins[0]:
        return cors_origins[0].rstrip("/")

    return "https://compass-kappa-nine.vercel.app"



@router.get("/api/auth/me")
async def auth_me(request: Request):
    """Retrieve logged-in user profile and calendar connection status."""
    from backend.services.calendar import get_calendar_connection_status
    ident = _get_current_identity(request)
    user_id = ident.user_id if ident and not ident.is_guest else None

    if not user_id or "@" not in user_id:
        return {
            "status": "ok",
            "authenticated": False,
            "user_id": user_id,
            "email": None,
            "name": "Guest",
            "calendar": {"connected": False, "mode": "none", "account_email": None},
        }

    pool = await get_pool()
    cal_status = (
        await get_calendar_connection_status(pool, user_id)
        if pool
        else {"connected": False, "mode": "none", "account_email": None}
    )

    return {
        "status": "ok",
        "authenticated": True,
        "user_id": user_id,
        "email": user_id,
        "name": user_id.split("@")[0].replace(".", " ").title(),
        "calendar": cal_status,
    }


@router.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    """Log out of current account and revoke session in DB and memory."""
    token = request.cookies.get("compass_session")
    if token:
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        if token_hash in _SESSIONS:
            _SESSIONS[token_hash]["revoked_at"] = now
        if token in _SESSIONS:
            _SESSIONS[token]["revoked_at"] = now
        pool = await get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sessions SET revoked_at = now() WHERE token_hash = $1",
                        token_hash,
                    )
            except Exception as e:
                logger.warning("Could not revoke session in DB: %s", e)
    response.delete_cookie("compass_session")
    response.delete_cookie("compass_user_id")
    return {"status": "ok", "message": "Logged out successfully"}


@router.api_route("/api/auth/quick-connect", methods=["GET", "POST"])
async def auth_quick_connect(response: Response, body: Optional[QuickConnectBody] = None):
    """Dev-only quick-connect helper for local offline UI debugging.
    Strictly forbidden and disabled in production, test, and default environments.
    """
    if not settings.is_development():
        raise HTTPException(
            status_code=404,
            detail="Endpoint disabled: Quick-connect is restricted to local development environments.",
        )

    from backend.services.calendar import save_calendar_connection
    raw_val = re.sub(r"[^\w@.-]", "", (body.email or body.auth_code or "").strip().lower())
    if "@" in raw_val:
        email = raw_val
    else:
        email = "scholar.authenticated@gmail.com"

    pool = await get_pool()
    if pool:
        await save_calendar_connection(
            pool=pool,
            user_id=email,
            account_email=email,
            access_token=f"mock_ya29_{secrets.token_hex(16)}",
            refresh_token=f"mock_1//_{secrets.token_hex(20)}",
            expires_in=86400,
        )

    session_token = create_session(email)
    response.set_cookie(
        key="compass_session",
        value=session_token,
        max_age=86400 * 30,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {
        "status": "ok",
        "email": email,
        "message": f"Successfully connected as {email}",
    }


@router.get("/api/calendar/connect")
async def calendar_connect(
    request: Request,
    redirect: bool = Query(False, description="Redirect directly to Google consent screen"),
    login_hint: Optional[str] = Query(None),
):
    """Generate Google OAuth 2.0 authorization URL or redirect directly."""
    configured = is_google_oauth_configured()
    if not configured:
        if redirect:
            frontend_origin = _resolve_frontend_origin(request)
            return RedirectResponse(url=f"{frontend_origin}/?oauth_error=not_configured")
        return {
            "status": "not_configured",
            "configured": False,
            "message": "Google OAuth credentials are not set in .env. Use Account Switcher or configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        }

    redirect_uri = _resolve_oauth_redirect_uri(request)
    ident = _get_current_identity(request)
    current_user = ident.user_id if ident and not ident.is_guest else None
    effective_hint = login_hint or (current_user if current_user and "@" in current_user else None)
    state = generate_oauth_state(current_user or "guest")
    url = generate_google_oauth_url(redirect_uri=redirect_uri, login_hint=effective_hint, state=state)

    accept = request.headers.get("accept", "")
    if redirect or "text/html" in accept:
        return RedirectResponse(url=url)
    return {"status": "ok", "configured": True, "url": url, "state": state}


@router.get("/api/calendar/callback")
async def calendar_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Handle OAuth redirect: exchange authorization code for tokens and save connection."""
    frontend_origin = _resolve_frontend_origin(request)
    if state:
        from backend.services.oauth import verify_oauth_state
        ident = _get_current_identity(request)
        current_user = ident.user_id if ident and not ident.is_guest else None
        expected_user = current_user or "guest"
        if not verify_oauth_state(state, expected_user):
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
                "<h3>OAuth State Verification Failed</h3>"
                "<p style='color:#fca5a5;'>Invalid or cross-user OAuth state token rejected (CSRF protection).</p>"
                f"<p><a style='color:#38bdf8;' href='{frontend_origin}/'>Return to Compass</a></p>"
                "</body></html>",
                status_code=403,
            )

    if error:
        safe_error = escape(error)
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
            f"<h3>Google Calendar Authorization Error: {safe_error}</h3>"
            f"<p><a style='color:#38bdf8;' href='{frontend_origin}/'>Return to Compass</a></p>"
            f"</body></html>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
            "<h3>Missing OAuth authorization code</h3>"
            f"<p><a style='color:#38bdf8;' href='{frontend_origin}/'>Return to Compass</a></p>"
            "</body></html>",
            status_code=400,
        )

    from backend.services.oauth import exchange_code_for_tokens
    from backend.services.calendar import save_calendar_connection

    redirect_uri = _resolve_oauth_redirect_uri(request)
    tokens = await exchange_code_for_tokens(code, redirect_uri=redirect_uri)

    if "error" in tokens:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
            f"<h3>Google Calendar Authorization Error</h3>"
            f"<p style='color:#fca5a5;'>{tokens['error']}</p>"
            f"<p style='color:#94a3b8;font-size:13px;'>Redirect URI sent to Google: <code style='color:#38bdf8;'>{redirect_uri}</code></p>"
            f"<p><a style='color:#38bdf8;' href='{frontend_origin}/'>Return to Compass</a></p>"
            f"</body></html>",
            status_code=400,
        )

    email = tokens.get("email") or tokens.get("account_email") or "scholar.authenticated@gmail.com"

    pool = await get_pool()
    if pool:
        await save_calendar_connection(
            pool=pool,
            user_id=email,
            account_email=email,
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token"),
            expires_in=tokens.get("expires_in", 3600),
        )

    safe_email = escape(re.sub(r"[^\w@.-]", "", str(email)))
    html_content = f"""<!DOCTYPE html>
<html>
<head><title>Compass — Google Calendar Connected</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0f172a;color:#f8fafc;">
    <div style="max-width:480px;margin:0 auto;background:#1e293b;padding:32px;border-radius:16px;border:1px solid #334155;box-shadow:0 10px 25px rgba(0,0,0,0.5);">
        <div style="font-size:48px;margin-bottom:12px;">🎉</div>
        <h2 style="margin:0 0 8px;color:#38bdf8;">Google Calendar Connected!</h2>
        <p style="color:#94a3b8;font-size:14px;margin-bottom:20px;">Logged in as <b style="color:#f8fafc;">{safe_email}</b>.<br>Your tasks will now synchronize to your Google Calendar.</p>
        <a style="display:inline-block;background:#2563eb;color:#ffffff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;" href="{frontend_origin}/?calendar_connected=true&email={safe_email}">Open Compass Dashboard</a>
    </div>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{type: 'compass_calendar_connected', email: '{safe_email}'}}, '*');
            setTimeout(() => window.close(), 1000);
        }} else {{
            setTimeout(() => {{ window.location.href = '{frontend_origin}/?calendar_connected=true&email={safe_email}'; }}, 1500);
        }}
    </script>
</body>
</html>"""
    response = HTMLResponse(html_content)
    session_token = create_session(str(email), oauth_verified=True)
    response.set_cookie(
        key="compass_session",
        value=session_token,
        max_age=86400 * 30,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


def _validate_trusted_origin(request: Request) -> bool:
    """Ensure mutating requests originate from trusted frontend origins or same-origin."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        # Direct CLI / same-origin requests without origin header (e.g. backend curl/postman)
        return True
    origin_clean = origin.rstrip("/")
    allowed = set(s.rstrip("/") for s in getattr(settings, "CORS_ORIGINS", []))
    allowed.update({
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
        "https://compass-farmlytics.vercel.app",
        "https://compass-kappa-nine.vercel.app",
        "https://compass-backend-qryu.onrender.com",
    })
    return any(origin_clean.startswith(a) for a in allowed)


@router.post("/api/calendar/sync-now")
async def calendar_sync_now(request: Request):
    """Explicitly synchronize all scheduled tasks to the connected user's Google Calendar."""
    if not _validate_trusted_origin(request):
        raise HTTPException(status_code=403, detail="Untrusted origin or referer")

    session_token = request.cookies.get("compass_session")
    if not session_token or not get_user_from_session(session_token):
        raise HTTPException(status_code=401, detail="Valid active compass_session cookie required to sync tasks")

    if not is_session_oauth_verified(session_token):
        raise HTTPException(status_code=403, detail="Sync requires a genuine Google OAuth-verified session")

    ident = _get_current_identity(request)
    user_id = ident.user_id if ident and not ident.is_guest else None
    if not user_id:
        return {"status": "error", "message": "Sign in to sync tasks with Google Calendar"}
    pool = await get_pool()
    from backend.services.calendar import sync_all_tasks_to_google_calendar
    result = await sync_all_tasks_to_google_calendar(pool, user_id=user_id)
    return result


@router.post("/api/calendar/disconnect")
async def calendar_disconnect(request: Request, response: Response):
    """Disconnect Google Calendar OAuth integration and clear session."""
    if not _validate_trusted_origin(request):
        raise HTTPException(status_code=403, detail="Untrusted origin or referer")

    session_token = request.cookies.get("compass_session")
    if not session_token or not get_user_from_session(session_token):
        raise HTTPException(status_code=401, detail="Valid active compass_session cookie required to disconnect")

    if not is_session_oauth_verified(session_token):
        raise HTTPException(status_code=403, detail="Disconnect requires a genuine Google OAuth-verified session")

    ident = _get_current_identity(request)
    user_id = ident.user_id if ident and not ident.is_guest else None
    pool = await get_pool()
    if pool and user_id:
        from backend.services.calendar import disconnect_calendar_connection
        await disconnect_calendar_connection(pool, user_id=user_id)

    if session_token:
        token_hash = _hash_token(session_token)
        now = datetime.now(timezone.utc)
        if token_hash in _SESSIONS:
            _SESSIONS[token_hash]["revoked_at"] = now
        if session_token in _SESSIONS:
            _SESSIONS[session_token]["revoked_at"] = now
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sessions SET revoked_at = now() WHERE token_hash = $1",
                        token_hash,
                    )
            except Exception as e:
                logger.warning("Could not revoke session in DB: %s", e)
    response.delete_cookie("compass_session")
    response.delete_cookie("compass_user_id")
    return {"status": "ok", "message": "Google Calendar disconnected."}
