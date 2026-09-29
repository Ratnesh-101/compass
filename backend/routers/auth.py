"""
Compass — Authentication and Google Calendar OAuth Endpoints.
"""

import logging
import re
import secrets
import urllib.parse
from html import escape
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import get_settings
from backend.dependencies import _get_current_user_id
from backend.memory.db import get_pool
from backend.models import SelectAccountBody, QuickConnectBody
from backend.services.oauth import generate_google_oauth_url, is_google_oauth_configured

logger = logging.getLogger("compass.routers.auth")
settings = get_settings()

router = APIRouter(tags=["auth"])

# In-memory session store mapping opaque tokens to session metadata
_SESSIONS: dict[str, dict] = {}


def create_session(user_id: str, oauth_verified: bool = False) -> str:
    """Generate an opaque session token and store mapping to user ID and verification status."""
    token = secrets.token_hex(24)
    _SESSIONS[token] = {
        "user_id": user_id,
        "oauth_verified": bool(oauth_verified),
    }
    return token


def get_user_from_session(token: str) -> Optional[str]:
    """Look up user identity from an opaque session token."""
    sess = _SESSIONS.get(token)
    if isinstance(sess, dict):
        return sess.get("user_id")
    return sess if isinstance(sess, str) else None


def is_session_oauth_verified(token: str) -> bool:
    """Check if the session was issued by the genuine Google OAuth callback handler."""
    sess = _SESSIONS.get(token)
    if isinstance(sess, dict):
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


@router.get("/api/auth/me")
async def auth_me(request: Request):
    """Retrieve logged-in user profile and calendar connection status."""
    from backend.services.calendar import get_calendar_connection_status
    user_id = _get_current_user_id(request)

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


@router.post("/api/auth/select-account")
async def auth_select_account(body: SelectAccountBody, response: Response):
    """Select or switch active user account for memory and calendar isolation."""
    raw_email = (body.email or body.user_id or "").strip().lower()
    email = re.sub(r"[^\w@.-]", "", raw_email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")

    session_token = create_session(email)
    response.set_cookie(
        key="compass_session",
        value=session_token,
        max_age=86400 * 365,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {
        "status": "ok",
        "user_id": email,
        "email": email,
        "name": email.split("@")[0].replace(".", " ").title(),
        "message": f"Switched account to {email}",
    }


@router.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    """Log out of current account and clear session cookies."""
    token = request.cookies.get("compass_session")
    if token:
        _SESSIONS.pop(token, None)
    response.delete_cookie("compass_session")
    response.delete_cookie("compass_user_id")
    return {"status": "ok", "message": "Logged out successfully"}


@router.post("/api/auth/quick-connect")
async def auth_quick_connect(body: QuickConnectBody, response: Response):
    """Quick-login with user account for instant access and testing."""
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
            return RedirectResponse(url="/?oauth_error=not_configured")
        return {
            "status": "not_configured",
            "configured": False,
            "message": "Google OAuth credentials are not set in .env. Use Account Switcher or configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        }

    redirect_uri = _resolve_oauth_redirect_uri(request)
    current_user = _get_current_user_id(request)
    effective_hint = login_hint or (current_user if current_user and "@" in current_user else None)
    url = generate_google_oauth_url(redirect_uri=redirect_uri, login_hint=effective_hint)

    accept = request.headers.get("accept", "")
    if redirect or "text/html" in accept:
        return RedirectResponse(url=url)
    return {"status": "ok", "configured": True, "url": url}


@router.get("/api/calendar/callback")
async def calendar_callback(
    request: Request,
    code: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Handle OAuth redirect: exchange authorization code for tokens and save connection."""
    if error:
        safe_error = escape(error)
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
            f"<h3>Google Calendar Authorization Error: {safe_error}</h3>"
            f"<p><a style='color:#38bdf8;' href='/'>Return to Compass</a></p>"
            f"</body></html>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:40px;background:#0f172a;color:#f87171;'>"
            "<h3>Missing OAuth authorization code</h3>"
            "<p><a style='color:#38bdf8;' href='/'>Return to Compass</a></p>"
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
            f"<p><a style='color:#38bdf8;' href='/'>Return to Compass</a></p>"
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
        <a style="display:inline-block;background:#2563eb;color:#ffffff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;" href="/?calendar_connected=true&email={safe_email}">Open Compass Dashboard</a>
    </div>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{type: 'compass_calendar_connected', email: '{safe_email}'}}, '*');
            setTimeout(() => window.close(), 1000);
        }} else {{
            setTimeout(() => {{ window.location.href = '/?calendar_connected=true&email={safe_email}'; }}, 1500);
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

    user_id = _get_current_user_id(request)
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

    user_id = _get_current_user_id(request)
    pool = await get_pool()
    if pool and user_id:
        from backend.services.calendar import disconnect_calendar_connection
        await disconnect_calendar_connection(pool, user_id=user_id)

    if session_token:
        _SESSIONS.pop(session_token, None)
    response.delete_cookie("compass_session")
    response.delete_cookie("compass_user_id")
    return {"status": "ok", "message": "Google Calendar disconnected."}
