"""
Compass — Google OAuth 2.0 Integration & Token Management.

Provides:
1. Google OAuth authorization URL construction (read-only calendar scope).
2. Token exchange (with mock fallback for offline/development mode).
3. Token encryption at rest using authenticated symmetric cipher.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
import logging

import httpx

from backend.config import get_settings

logger = logging.getLogger("compass.oauth")

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
GOOGLE_OAUTH_SCOPE_STRING = " ".join(GOOGLE_SCOPES)
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


# ---------------------------------------------------------------------------
# Token Encryption at Rest (HMAC-SHA256 Authenticated Symmetric Stream Cipher)
# ---------------------------------------------------------------------------

def _get_encryption_key() -> bytes:
    settings = get_settings()
    if settings.is_production():
        settings.validate_production_secrets()
    secret = (
        getattr(settings, "TOKEN_ENCRYPTION_KEY", None)
        or getattr(settings, "AUTH_TOKEN", None)
        or "compass-secret-encryption-key-salt"
    )
    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        b"compass_token_salt_fixed",
        iterations=100_000,
        dklen=32,
    )


def encrypt_token(plain_text: Optional[str]) -> Optional[str]:
    """Encrypt a plain text token string for secure storage in calendar_connections."""
    if plain_text is None:
        return None
    if not plain_text:
        return ""
    key = _get_encryption_key()
    nonce = secrets.token_bytes(16)
    
    # Generate keystream using HMAC-SHA256 of key + nonce + counter
    data_bytes = plain_text.encode("utf-8")
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(data_bytes):
        keystream.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    
    cipher_bytes = bytes(b ^ k for b, k in zip(data_bytes, keystream[:len(data_bytes)]))
    tag = hmac.new(key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]
    
    # Format: base64(nonce + tag + cipher_bytes)
    return "enc:" + base64.urlsafe_b64encode(nonce + tag + cipher_bytes).decode("utf-8")


def decrypt_token(enc_text: Optional[str]) -> Optional[str]:
    """Decrypt an encrypted token string retrieved from calendar_connections."""
    if enc_text is None:
        return None
    if not enc_text or not enc_text.startswith("enc:"):
        return enc_text or ""
    try:
        raw = base64.urlsafe_b64decode(enc_text[4:].encode("utf-8"))
        if len(raw) < 32:
            return ""
        nonce = raw[:16]
        tag = raw[16:32]
        cipher_bytes = raw[32:]
        key = _get_encryption_key()
        
        expected_tag = hmac.new(key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            logger.warning("Token decryption HMAC verification failed")
            return ""
        
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(cipher_bytes):
            keystream.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        
        plain_bytes = bytes(b ^ k for b, k in zip(cipher_bytes, keystream[:len(cipher_bytes)]))
        return plain_bytes.decode("utf-8")
    except Exception as e:
        logger.warning(f"Error decrypting token: {e}")
        return ""


# ---------------------------------------------------------------------------
# OAuth URL Generation, Token Exchange, & Refresh
# ---------------------------------------------------------------------------

def is_google_oauth_configured() -> bool:
    """Return True if real Google OAuth client credentials are configured in environment or settings."""
    settings = get_settings()
    c_id = getattr(settings, "GOOGLE_CLIENT_ID", None) or os.getenv("GOOGLE_CLIENT_ID", "")
    secret = getattr(settings, "GOOGLE_CLIENT_SECRET", None) or os.getenv("GOOGLE_CLIENT_SECRET", "")
    return bool(c_id and secret and not str(c_id).startswith("demo-"))


import asyncio
import time

# Replay protection cache: records consumed HMAC state signatures and their consumption timestamps
_CONSUMED_OAUTH_STATES: dict[str, float] = {}
_STATE_LOCK = asyncio.Lock()


def _get_state_secret() -> bytes:
    """Derive HMAC secret key for signing and verifying OAuth state.
    
    Checks COMPASS_STATE_SECRET, SECRET_KEY, TOKEN_ENCRYPTION_KEY, or AUTH_TOKEN.
    In production, enforces that production secrets are configured without insecure fallbacks.
    """
    settings = get_settings()
    if settings.is_production():
        settings.validate_production_secrets()
    secret = (
        os.getenv("COMPASS_STATE_SECRET")
        or os.getenv("SECRET_KEY")
        or getattr(settings, "TOKEN_ENCRYPTION_KEY", None)
        or getattr(settings, "AUTH_TOKEN", None)
    )
    if not secret:
        if settings.is_production():
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: Missing OAuth state secret "
                "(COMPASS_STATE_SECRET / SECRET_KEY / TOKEN_ENCRYPTION_KEY / AUTH_TOKEN)."
            )
        secret = "compass-dev-oauth-state-secret-salt"

    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        b"compass-calendar-oauth-state-salt-2026",
        iterations=100_000,
        dklen=32,
    )


async def record_consumed_state(
    sig: str,
    user_id: str,
    action: str,
    max_age_seconds: int = 600,
    pool: Any = None,
) -> bool:
    """Atomically record and consume OAuth state signature.
    
    If pool is provided: executes an atomic INSERT ON CONFLICT DO NOTHING in PostgreSQL.
    PostgreSQL's PRIMARY KEY uniqueness on state_sig guarantees that exactly ONE concurrent
    request can succeed across multiple workers, processes, or server restarts.
    Returns True if inserted (first use), False if already consumed.
    
    In production with a database pool, any database failure produces an operational error
    rather than silently falling back to insecure process-local replay protection.
    
    If pool is None: falls back to an asyncio.Lock-guaranteed atomic check-and-insert in memory.
    """
    settings = get_settings()
    if pool is not None:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)
            async with pool.acquire() as conn:
                res = await conn.execute(
                    """
                    INSERT INTO oauth_consumed_states (state_sig, user_id, action, consumed_at, expires_at)
                    VALUES ($1, $2, $3, now(), $4)
                    ON CONFLICT (state_sig) DO NOTHING
                    """,
                    sig,
                    user_id,
                    action,
                    expires_at,
                )
                if isinstance(res, str):
                    return res == "INSERT 0 1"
        except Exception as e:
            logger.error("CRITICAL: Database atomic state consumption failed on oauth_consumed_states: %s", e)
            if settings.is_production():
                raise RuntimeError(f"Database error during OAuth state consumption: {e}") from e
            logger.warning("Non-production environment: falling back to memory lock after DB error: %s", e)

    # In-memory atomic fallback with asyncio.Lock
    async with _STATE_LOCK:
        now = time.time()
        cutoff = now - 1800
        for k in list(_CONSUMED_OAUTH_STATES.keys()):
            if _CONSUMED_OAUTH_STATES[k] < cutoff:
                _CONSUMED_OAUTH_STATES.pop(k, None)
        if sig in _CONSUMED_OAUTH_STATES:
            return False
        _CONSUMED_OAUTH_STATES[sig] = now
        return True


async def cleanup_expired_oauth_states(pool: Any) -> int:
    """Prune consumed state records where expires_at < NOW().
    
    Safe because states past expires_at (600s TTL) are already expired and
    would be rejected by timestamp validation anyway.
    Never deletes records where expires_at >= NOW().
    """
    if pool is None:
        return 0
    try:
        async with pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM oauth_consumed_states WHERE expires_at < now()"
            )
            if isinstance(res, str) and res.startswith("DELETE "):
                return int(res.split(" ")[1])
    except Exception as e:
        logger.warning(f"Failed to prune expired oauth states: {e}")
    return 0


def _compute_state_sig(user_id: str, ts: int, nonce: str = "", action: str = "") -> str:
    """Compute cryptographically authenticated signature for user ID, timestamp, nonce, and action."""
    key = _get_state_secret()
    if nonce or action:
        msg = f"{user_id.lower()}:{ts}:{nonce}:{action}".encode("utf-8")
    else:
        msg = f"{user_id.lower()}:{ts}".encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256",
        msg,
        key,
        iterations=1000,
        dklen=32,
    ).hex()


OAUTH_NONCE_COOKIE = "oauth_nonce"
OAUTH_NONCE_MAX_AGE_SECONDS = 600


def new_browser_nonce() -> str:
    """Random secret handed to the initiating browser in an HttpOnly cookie (login-CSRF binding)."""
    return secrets.token_urlsafe(32)


def _browser_nonce_digest(browser_nonce: str) -> str:
    return hashlib.sha256(browser_nonce.encode("utf-8")).hexdigest()


def browser_nonce_matches_state(state: str, browser_nonce: Optional[str]) -> bool:
    """True when the browser nonce cookie hashes to the nonce carried by the signed state.

    Only compares; authenticity of the state is verified by verify_and_consume_oauth_state,
    whose signature covers the nonce field.
    """
    if not state or not browser_nonce:
        return False
    try:
        raw = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 5:
            return False
        return hmac.compare_digest(parts[2], _browser_nonce_digest(browser_nonce))
    except Exception:
        return False


def generate_oauth_state(
    user_id: str, action: str = "google_calendar", browser_nonce: Optional[str] = None
) -> str:
    """Generate cryptographically HMAC-signed, unpredictable OAuth state bound to user_id, timestamp, and nonce.

    When browser_nonce is given, its SHA-256 digest is the signed nonce field, binding the state
    to the browser that holds the matching cookie.
    """
    clean_user = (user_id or "guest").lower().strip()
    ts = int(time.time())
    nonce = _browser_nonce_digest(browser_nonce) if browser_nonce else secrets.token_urlsafe(16)
    sig = _compute_state_sig(clean_user, ts, nonce, action)
    raw = f"{clean_user}:{ts}:{nonce}:{action}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


async def verify_and_consume_oauth_state(
    state: str,
    max_age_seconds: int = 600,
    expected_action: str = "google_calendar",
    pool: Any = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Verify that an OAuth state parameter is authentic, unexpired, and unplayed; atomically mark it consumed.
    
    Returns:
        (is_valid: bool, initiating_user_id: Optional[str], error_reason: Optional[str])
    """
    if not state or not isinstance(state, str):
        return False, None, "missing_state"

    try:
        raw = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        now = int(time.time())

        if len(parts) == 5:
            user_id_part, ts_str, nonce, action, sig = parts
            if action != expected_action:
                return False, None, "invalid_action"
            ts = int(ts_str)
            if abs(now - ts) > max_age_seconds:
                return False, None, "expired_state"
            expected_sig = _compute_state_sig(user_id_part, ts, nonce, action)
            if not hmac.compare_digest(sig, expected_sig):
                return False, None, "invalid_state"
            # Atomically consume state (PostgreSQL primary key or asyncio.Lock)
            consumed = await record_consumed_state(sig, user_id_part, action, max_age_seconds, pool=pool)
            if not consumed:
                return False, None, "replayed_state"
            return True, user_id_part, None

        if len(parts) == 3:
            # Backward compatibility with legacy 3-part states (user_id:ts:sig)
            user_id_part, ts_str, sig = parts
            ts = int(ts_str)
            if abs(now - ts) > max_age_seconds:
                return False, None, "expired_state"
            expected_sig = _compute_state_sig(user_id_part, ts)
            if not hmac.compare_digest(sig, expected_sig):
                return False, None, "invalid_state"
            consumed = await record_consumed_state(sig, user_id_part, expected_action, max_age_seconds, pool=pool)
            if not consumed:
                return False, None, "replayed_state"
            return True, user_id_part, None

        return False, None, "invalid_state"
    except RuntimeError:
        raise
    except Exception as e:
        logger.debug(f"State verification failed: {e}")
        return False, None, "invalid_state"


def verify_oauth_state(state: str, expected_user_id: str, max_age_seconds: int = 600) -> bool:
    """Verify that an OAuth state parameter is valid, unexpired, and strictly bound to expected_user_id."""
    if not state or not expected_user_id:
        return False
    try:
        raw = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        now = int(time.time())
        if len(parts) == 5:
            user_id_part, ts_str, nonce, action, sig = parts
            ts = int(ts_str)
            if abs(now - ts) > max_age_seconds:
                return False
            expected_sig = _compute_state_sig(user_id_part, ts, nonce, action)
            if not hmac.compare_digest(sig, expected_sig):
                return False
            clean_expected = (expected_user_id or "guest").lower().strip()
            return user_id_part.lower() == clean_expected
        if len(parts) == 3:
            user_id_part, ts_str, sig = parts
            ts = int(ts_str)
            if abs(now - ts) > max_age_seconds:
                return False
            expected_sig = _compute_state_sig(user_id_part, ts)
            if not hmac.compare_digest(sig, expected_sig):
                return False
            clean_expected = (expected_user_id or "guest").lower().strip()
            return user_id_part.lower() == clean_expected
        return False
    except Exception:
        return False


def generate_google_oauth_url(
    redirect_uri: str = "http://localhost:8000/api/calendar/callback",
    state: Optional[str] = None,
    client_id: Optional[str] = None,
    login_hint: Optional[str] = None,
) -> str:
    """Generate the Google OAuth 2.0 authorization URL with calendar and profile scopes.
    
    Always includes prompt='select_account consent' so Google will present the account
    selection screen rather than silently logging into an existing browser session.
    """
    settings = get_settings()
    c_id = client_id or getattr(settings, "GOOGLE_CLIENT_ID", None) or os.getenv("GOOGLE_CLIENT_ID", "demo-compass-client-id.apps.googleusercontent.com")
    
    state_token = state or secrets.token_urlsafe(16)
    params = {
        "client_id": c_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPE_STRING,
        "access_type": "offline",
        "prompt": "select_account consent",
        "state": state_token,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str = "http://localhost:8000/api/calendar/callback",
) -> Dict[str, Any]:
    """Exchange authorization code for access and refresh tokens, plus user profile."""
    settings = get_settings()
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", None) or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", None) or os.getenv("GOOGLE_CLIENT_SECRET", "")

    # If demo/mock credentials or mock test code, provide simulated authenticated response ONLY in dev/test
    is_dev = getattr(settings, "ENVIRONMENT", "").lower() in ("development", "test")
    if not client_id or not client_secret or client_id.startswith("demo-") or "mock" in code.lower() or code.startswith("test"):
        if not is_dev:
            raise ValueError("Google OAuth credentials not configured in production or invalid authorization code.")
        logger.info("Using simulated OAuth token exchange (demo mode credentials or test code)")
        return {
            "access_token": f"mock_ya29_{secrets.token_hex(16)}",
            "refresh_token": f"mock_1//_{secrets.token_hex(20)}",
            "expires_in": 3600,
            "email": "scholar.authenticated@gmail.com",
            "name": "Compass Scholar",
            "picture": "https://lh3.googleusercontent.com/a/default-user",
            "account_email": "scholar.authenticated@gmail.com",
            "token_type": "Bearer",
            "scope": GOOGLE_OAUTH_SCOPE_STRING,
            "mode": "live_simulated",
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if resp.status_code != 200:
                err_type = "unknown_error"
                try:
                    err_json = resp.json()
                    err_type = err_json.get("error") or "error_response"
                except Exception:
                    pass
                logger.error(f"Google token endpoint returned HTTP {resp.status_code} (error_type={err_type})")
                return {
                    "error": f"Google Token Exchange Failed ({resp.status_code}): {err_type}",
                    "status_code": resp.status_code,
                }

            token_data = resp.json()
            access_token = token_data.get("access_token")

            # Fetch account email, name, and picture from userinfo
            email = None
            name = "Compass User"
            picture = ""
            try:
                u_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if u_resp.status_code == 200:
                    u_json = u_resp.json()
                    email = u_json.get("email")
                    name = u_json.get("name") or name
                    picture = u_json.get("picture") or picture
                    email_verified = u_json.get("verified_email", u_json.get("email_verified", True))
                    if not email_verified:
                        return {
                            "error": "Google account email is not verified.",
                            "status_code": 400,
                        }
                else:
                    logger.error(f"Failed to retrieve userinfo from Google: status {u_resp.status_code}")
                    return {
                        "error": f"Failed to retrieve user profile from Google (status {u_resp.status_code}).",
                        "status_code": u_resp.status_code,
                    }
            except Exception as ue:
                logger.error(f"Exception fetching Google userinfo: {ue}")
                return {
                    "error": "Failed to retrieve user profile from Google.",
                    "status_code": 500,
                }

            if not email or "@" not in email:
                return {
                    "error": "Google profile did not provide a valid email address.",
                    "status_code": 400,
                }

            return {
                "access_token": access_token,
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": token_data.get("expires_in", 3600),
                "email": email,
                "name": name,
                "picture": picture,
                "account_email": email,
                "scope": token_data.get("scope", GOOGLE_OAUTH_SCOPE_STRING),
                "mode": "live",
            }
    except Exception as e:
        logger.error(f"Error during token exchange: {e}")
        if is_dev and ("mock" in code.lower() or code.startswith("test")):
            return {
                "access_token": f"mock_ya29_{secrets.token_hex(16)}",
                "refresh_token": f"mock_1//_{secrets.token_hex(20)}",
                "expires_in": 3600,
                "email": "scholar.authenticated@gmail.com",
                "name": "Compass Scholar",
                "picture": "https://lh3.googleusercontent.com/a/default-user",
                "account_email": "scholar.authenticated@gmail.com",
                "mode": "live_simulated",
            }
        return {
            "error": "Failed to complete token exchange with Google.",
            "mode": "error",
        }


async def refresh_google_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Use a refresh token to fetch a new access token from Google."""
    settings = get_settings()
    c_id = client_id or getattr(settings, "GOOGLE_CLIENT_ID", None) or os.getenv("GOOGLE_CLIENT_ID", "")
    c_secret = client_secret or getattr(settings, "GOOGLE_CLIENT_SECRET", None) or os.getenv("GOOGLE_CLIENT_SECRET", "")

    if not c_id or not c_secret or c_id.startswith("demo-") or refresh_token.startswith("mock_"):
        if getattr(settings, "ENVIRONMENT", "").lower() not in ("development", "test"):
            raise ValueError("Google OAuth credentials not configured in production.")
        return {
            "access_token": f"mock_ya29_{secrets.token_hex(16)}",
            "expires_in": 3600,
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": c_id,
                    "client_secret": c_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "access_token": data.get("access_token"),
                    "expires_in": data.get("expires_in", 3600),
                }
            err_type = "unknown_error"
            try:
                err_type = resp.json().get("error") or "error_response"
            except Exception:
                pass
            logger.warning(f"Token refresh failed HTTP {resp.status_code} (error_type={err_type})")
            return None
    except Exception as e:
        logger.error(f"Token refresh network error: {e}")
        return None
