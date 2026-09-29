"""
Compass — Common API Dependencies and Rate Limiters.
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.config import get_settings

import hmac
from backend.services.security import get_client_ip

# ---------------------------------------------------------------------------
# Rate Limiter — Sliding-window per client IP (30 requests/minute on chat)
# ---------------------------------------------------------------------------
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_rate_store: dict = defaultdict(deque)  # ip -> deque of timestamps

_AGENT_RATE_LIMIT_WINDOW_SECONDS = 60
_AGENT_RATE_LIMIT_MAX_REQUESTS = 10
_agent_rate_store: dict = defaultdict(deque)  # ip -> deque of timestamps


async def rate_limit(request: Request) -> None:
    """Sliding-window rate limiter: 30 requests/min per client IP on chat endpoints.
    Returns HTTP 429 Too Many Requests with Retry-After header when exceeded.
    """
    client_ip = get_client_ip(request)
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    q = _rate_store[client_ip]
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= _RATE_LIMIT_MAX_REQUESTS:
        retry_after = int(_RATE_LIMIT_WINDOW_SECONDS - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {_RATE_LIMIT_MAX_REQUESTS} requests per minute per IP.",
            headers={"Retry-After": str(retry_after)},
        )

    q.append(now)


async def agent_rate_limit(request: Request) -> None:
    """Separate sliding-window rate limiter for agent runs: 10 requests/min per client IP.
    Returns HTTP 429 Too Many Requests with Retry-After header when exceeded.
    """
    client_ip = get_client_ip(request)
    now = time.monotonic()
    window_start = now - _AGENT_RATE_LIMIT_WINDOW_SECONDS

    q = _agent_rate_store[client_ip]
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= _AGENT_RATE_LIMIT_MAX_REQUESTS:
        retry_after = int(_AGENT_RATE_LIMIT_WINDOW_SECONDS - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Agent rate limit exceeded. Max {_AGENT_RATE_LIMIT_MAX_REQUESTS} runs per minute per IP.",
            headers={"Retry-After": str(retry_after)},
        )

    q.append(now)


# ---------------------------------------------------------------------------
# Auth Dependency — Bearer Token
# ---------------------------------------------------------------------------
_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Validate the Authorization: Bearer <token> header against AUTH_TOKEN.

    Fails closed in production if AUTH_TOKEN is missing or set to insecure default.
    Uses constant-time comparison to prevent timing attacks.
    """
    settings = get_settings()

    # Fail closed in production if token is insecure
    if settings.is_production():
        if not settings.AUTH_TOKEN or settings.AUTH_TOKEN.strip() in (
            settings.DEFAULT_DEV_TOKEN,
            "compass-token",
            "test-token",
        ):
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: production authentication token is not securely configured.",
            )

    if not settings.AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not hmac.compare_digest(credentials.credentials, settings.AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return credentials.credentials


# ---------------------------------------------------------------------------
# User Identity Helper
# ---------------------------------------------------------------------------
def _get_current_user_id(request: Request) -> Optional[str]:
    """Resolve current user identity strictly from headers or cookies."""
    user_header = request.headers.get("x-user-id")
    if user_header and user_header.strip():
        return user_header.strip().lower()

    session_token = request.cookies.get("compass_session")
    if session_token:
        try:
            from backend.routers.auth import get_user_from_session
            user = get_user_from_session(session_token)
            if user:
                return user.lower()
        except Exception:
            pass

    cookie_user = request.cookies.get("compass_user_id")
    if cookie_user and cookie_user.strip():
        import urllib.parse
        return urllib.parse.unquote(cookie_user.strip()).lower()
    return None


def _get_or_create_user_id(request: Request) -> str:
    """Resolve current user identity, falling back to a deterministic guest identity.

    Guarantees every task or memory mutation is bound to an isolated user or guest
    workspace identity rather than leaving ownership unassigned (NULL).
    """
    uid = _get_current_user_id(request)
    if uid:
        return uid
    client_ip = get_client_ip(request)
    import hashlib
    h = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:12]
    return f"guest_{h}"


def _now_iso() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
