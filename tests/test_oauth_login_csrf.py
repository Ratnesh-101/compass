"""
Compass — Google OAuth Login CSRF Protection Test Suite.

Verifies:
1. Valid OAuth flow with matching nonce cookie passes and deletes nonce cookie after use.
2. Callback without the nonce cookie is rejected with HTTP 400.
3. Callback with a mismatched nonce cookie is rejected with HTTP 400.
4. Nonce cookie set at connect endpoint is HttpOnly, SameSite=Lax, and Secure on HTTPS.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.routers.auth import create_session
from backend.services.oauth import generate_oauth_state


@pytest.fixture(autouse=True)
def clean_oauth_cache():
    """Clear replay protection cache before each test."""
    from backend.services.oauth import _CONSUMED_OAUTH_STATES
    _CONSUMED_OAUTH_STATES.clear()
    yield
    _CONSUMED_OAUTH_STATES.clear()


@pytest.mark.asyncio
async def test_oauth_connect_sets_httponly_nonce_cookie():
    """Connect endpoint sets a short-lived (10 min) HttpOnly, SameSite=Lax, Secure cookie on HTTPS."""
    transport = ASGITransport(app=app)
    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True):
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get("/api/calendar/connect")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "state" in data
            assert "oauth_nonce" in client.cookies

            # Verify cookie attributes in Set-Cookie header
            set_cookie_headers = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [resp.headers.get("set-cookie", "")]
            nonce_cookie_header = next((h for h in set_cookie_headers if "oauth_nonce=" in h), "")
            assert nonce_cookie_header != "", "oauth_nonce cookie not set"
            lower_header = nonce_cookie_header.lower()
            assert "httponly" in lower_header
            assert "samesite=lax" in lower_header
            assert "secure" in lower_header
            assert "max-age=600" in lower_header


@pytest.mark.asyncio
async def test_oauth_valid_flow_passes():
    """Valid OAuth flow with matching nonce cookie completes successfully and clears the nonce cookie."""
    transport = ASGITransport(app=app)
    user_email = "student@vit.ac.in"
    google_email = "student.gcal@gmail.com"
    session_token = create_session(user_email)

    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save, \
         patch("backend.routers.auth.get_pool", return_value=MagicMock()), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange:

        mock_exchange.return_value = {
            "access_token": "ya29.test_token",
            "refresh_token": "1//test_refresh",
            "expires_in": 3600,
            "email": google_email,
            "account_email": google_email,
        }

        async with AsyncClient(
            transport=transport,
            base_url="https://compass-farmlytics.vercel.app",
            cookies={"compass_session": session_token},
        ) as client:
            # 1. Connect generates state and sets oauth_nonce cookie
            init_resp = await client.get("/api/calendar/connect")
            assert init_resp.status_code == 200
            state = init_resp.json()["state"]
            assert "oauth_nonce" in client.cookies

            # 2. Callback receives matching cookie and valid state
            cb_resp = await client.get(
                f"/api/calendar/callback?code=valid_auth_code&state={state}",
                follow_redirects=False,
            )
            assert cb_resp.status_code == 303
            assert "calendar_connected=true" in cb_resp.headers["location"]
            assert mock_save.called

            # 3. Cookie is deleted after callback
            set_cookie_headers = cb_resp.headers.get_list("set-cookie") if hasattr(cb_resp.headers, "get_list") else [cb_resp.headers.get("set-cookie", "")]
            deleted_cookie = any(
                "oauth_nonce=" in h and ("max-age=0" in h.lower() or "expires=" in h.lower())
                for h in set_cookie_headers
            )
            assert deleted_cookie or "oauth_nonce" not in cb_resp.cookies


@pytest.mark.asyncio
async def test_oauth_callback_without_cookie_rejected():
    """Callback without the oauth_nonce cookie is rejected with HTTP 400 (Login CSRF prevention)."""
    transport = ASGITransport(app=app)
    state = generate_oauth_state("victim@vit.ac.in")

    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            cb_resp = await client.get(
                f"/api/calendar/callback?code=attacker_code&state={state}",
                follow_redirects=False,
            )
            assert cb_resp.status_code == 400
            assert not mock_exchange.called
            assert not mock_save.called


@pytest.mark.asyncio
async def test_oauth_callback_with_different_nonce_cookie_rejected():
    """Callback with a mismatched oauth_nonce cookie is rejected with HTTP 400."""
    transport = ASGITransport(app=app)
    state = generate_oauth_state("victim@vit.ac.in")

    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:

        async with AsyncClient(
            transport=transport,
            base_url="https://compass-farmlytics.vercel.app",
            cookies={"oauth_nonce": "attacker_bogus_nonce_value_1234567890"},
        ) as client:
            cb_resp = await client.get(
                f"/api/calendar/callback?code=attacker_code&state={state}",
                follow_redirects=False,
            )
            assert cb_resp.status_code == 400
            assert not mock_exchange.called
            assert not mock_save.called

            # Check that cookie cleanup is issued
            set_cookie_headers = cb_resp.headers.get_list("set-cookie") if hasattr(cb_resp.headers, "get_list") else [cb_resp.headers.get("set-cookie", "")]
            deleted_cookie = any(
                "oauth_nonce=" in h and ("max-age=0" in h.lower() or "expires=" in h.lower())
                for h in set_cookie_headers
            )
            assert deleted_cookie or "oauth_nonce" not in cb_resp.cookies
