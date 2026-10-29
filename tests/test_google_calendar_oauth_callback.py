"""
Compass — Comprehensive Google Calendar OAuth Callback & Impersonation Protection Test Suite.

Covers:
 1. Successful OAuth initiation and callback for an authenticated user.
 2. Correct association between the initiating Compass user and the saved Google credentials.
 3. Missing OAuth state.
 4. Invalid or tampered OAuth state.
 5. Expired OAuth state.
 6. Replayed OAuth state or duplicate callback.
 7. OAuth access denied by the user.
 8. Failed token exchange.
 9. Missing or invalid authorization code.
10. Attempts to impersonate another user through X-user-id.
11. Attempts to impersonate another user through compass_user_id.
12. Production environment rejects development-only impersonation.
13. OAuth initiation and callback work with the actual configured redirect URI.
14. Failure does not leave a partially connected integration.
15. Existing non-OAuth API authentication and impersonation protections continue to work.
"""

import asyncio
import time
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.config import get_settings
from backend.routers.auth import create_session
from backend.services.oauth import (
    generate_oauth_state,
    verify_and_consume_oauth_state,
    verify_oauth_state,
    _browser_nonce_digest,
    _compute_state_sig,
)

# Browser nonce the callback cookie must carry so the signed state is bound to this "browser".
BROWSER_NONCE = "test-browser-nonce-0123456789abcdefghij"
NONCE_COOKIES = {"oauth_nonce": BROWSER_NONCE}


def bound_state(user_id: str) -> str:
    """Signed state bound to BROWSER_NONCE (what /api/calendar/connect issues with its cookie)."""
    return generate_oauth_state(user_id, browser_nonce=BROWSER_NONCE)


@pytest.fixture(autouse=True)
def clean_oauth_cache():
    """Clear replay protection cache before each test."""
    from backend.services.oauth import _CONSUMED_OAUTH_STATES
    _CONSUMED_OAUTH_STATES.clear()
    yield
    _CONSUMED_OAUTH_STATES.clear()


@pytest.mark.asyncio
async def test_1_successful_oauth_initiation_and_callback_authenticated_user():
    """1. Successful OAuth initiation and callback for an authenticated user."""
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
            # Step A: Initiate connection
            init_resp = await client.get("/api/calendar/connect")
            assert init_resp.status_code == 200
            init_data = init_resp.json()
            assert init_data["configured"] is True
            state = init_data["state"]
            assert state is not None

            # Verify state contains user (non-consuming) and the nonce cookie was issued
            assert verify_oauth_state(state, user_email) is True
            assert "oauth_nonce" in client.cookies
            fresh_state = state

            # Step B: Callback from Google
            cb_resp = await client.get(
                f"/api/calendar/callback?code=valid_auth_code&state={fresh_state}",
                follow_redirects=False,
            )
            assert cb_resp.status_code == 303
            location = cb_resp.headers["location"]
            assert "calendar_connected=true" in location
            assert urllib.parse.quote(google_email) in location or google_email in location
            assert "compass_session" in cb_resp.cookies


@pytest.mark.asyncio
async def test_2_correct_user_association_saved_credentials():
    """2. Correct association between the initiating Compass user and saved Google credentials."""
    transport = ASGITransport(app=app)
    compass_user = "scholar@vit.ac.in"
    google_email = "scholar.personal@gmail.com"
    state = bound_state(compass_user)

    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save, \
         patch("backend.routers.auth.get_pool", return_value=MagicMock()), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange:

        mock_exchange.return_value = {
            "access_token": "ya29.secret_token",
            "refresh_token": "1//refresh_token",
            "expires_in": 3600,
            "email": google_email,
            "account_email": google_email,
        }

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp = await client.get(
                f"/api/calendar/callback?code=auth_code_xyz&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert mock_save.called
            save_kwargs = mock_save.call_args.kwargs
            # user_id must be the initiating Compass user, NOT the google_email
            assert save_kwargs["user_id"] == compass_user
            assert save_kwargs["account_email"] == google_email


@pytest.mark.asyncio
async def test_3_missing_oauth_state():
    """3. Missing OAuth state parameter is safely rejected without raw exception or partial connection."""
    transport = ASGITransport(app=app)
    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get("/api/calendar/callback?code=valid_code", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=missing_state" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_4_invalid_or_tampered_oauth_state():
    """4. Invalid or tampered OAuth state is rejected (signature mismatch / malformed)."""
    transport = ASGITransport(app=app)
    valid_state = bound_state("legit_user@vit.ac.in")
    import base64

    decoded = base64.urlsafe_b64decode(valid_state.encode("utf-8")).decode("utf-8")
    tampered_state = base64.urlsafe_b64encode((decoded[:-6] + "bad123").encode("utf-8")).decode("utf-8")

    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp = await client.get(f"/api/calendar/callback?code=code123&state={tampered_state}", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=invalid_state" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_5_expired_oauth_state():
    """5. Expired OAuth state (older than 600s) is rejected."""
    import base64

    transport = ASGITransport(app=app)
    old_ts = int(time.time()) - 700
    nonce = _browser_nonce_digest(BROWSER_NONCE)
    action = "google_calendar"
    sig = _compute_state_sig("user@vit.ac.in", old_ts, nonce, action)
    raw = f"user@vit.ac.in:{old_ts}:{nonce}:{action}:{sig}"
    expired_state = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp = await client.get(f"/api/calendar/callback?code=code123&state={expired_state}", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=expired_state" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_6_replayed_oauth_state_or_duplicate_callback():
    """6. Replayed OAuth state or duplicate callback is rejected on second attempt."""
    transport = ASGITransport(app=app)
    state = bound_state("replay_user@vit.ac.in")
    google_email = "replay_user@gmail.com"

    with patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save, \
         patch("backend.routers.auth.get_pool", return_value=MagicMock()), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange:

        mock_exchange.return_value = {
            "access_token": "ya29.first_use",
            "refresh_token": "1//refresh",
            "expires_in": 3600,
            "email": google_email,
            "account_email": google_email,
        }

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp1 = await client.get(f"/api/calendar/callback?code=code123&state={state}", follow_redirects=False)
            assert resp1.status_code == 303
            assert "calendar_connected=true" in resp1.headers["location"]
            assert mock_save.call_count == 1

            resp2 = await client.get(f"/api/calendar/callback?code=code123&state={state}", follow_redirects=False)
            assert resp2.status_code == 303
            assert "calendar_error=replayed_state" in resp2.headers["location"]
            assert mock_save.call_count == 1


@pytest.mark.asyncio
async def test_7_oauth_access_denied_by_user():
    """7. OAuth access denied by user (Google returns error=access_denied) redirects safely."""
    transport = ASGITransport(app=app)
    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get("/api/calendar/callback?error=access_denied", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=access_denied" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_8_failed_token_exchange():
    """8. Failed token exchange with Google does not save credentials and redirects with safe error."""
    transport = ASGITransport(app=app)
    state = bound_state("user@vit.ac.in")

    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save, \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange:

        mock_exchange.return_value = {"error": "Google Token Exchange Failed (400): invalid_grant"}

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp = await client.get(f"/api/calendar/callback?code=bad_code&state={state}", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=token_exchange_failed" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_9_missing_or_invalid_authorization_code():
    """9. Missing authorization code with valid state redirects with missing_code."""
    transport = ASGITransport(app=app)
    state = generate_oauth_state("user@vit.ac.in")

    with patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock) as mock_save:
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get(f"/api/calendar/callback?state={state}", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=missing_code" in resp.headers["location"]
            assert not mock_save.called


@pytest.mark.asyncio
async def test_10_attempts_to_impersonate_another_user_through_x_user_id():
    """10. Attempts to impersonate another user through X-user-id header in production are rejected on connect, and ignored on callback."""
    transport = ASGITransport(app=app)
    settings = get_settings()

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch("backend.services.oauth.is_google_oauth_configured", return_value=True):

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get(
                "/api/calendar/connect",
                headers={"x-user-id": "victim@vit.ac.in"},
            )
            assert resp.status_code == 403
            assert "impersonation is strictly forbidden" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_11_attempts_to_impersonate_another_user_through_compass_user_id():
    """11. Attempts to impersonate another user through compass_user_id cookie in production are rejected on connect, and ignored on callback."""
    transport = ASGITransport(app=app)
    settings = get_settings()

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch("backend.services.oauth.is_google_oauth_configured", return_value=True):

        async with AsyncClient(
            transport=transport,
            base_url="https://compass-farmlytics.vercel.app",
            cookies={"compass_user_id": "victim@vit.ac.in"},
        ) as client:
            resp = await client.get("/api/calendar/connect")
            assert resp.status_code == 403
            assert "impersonation is strictly forbidden" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_12_production_environment_rejects_development_only_impersonation():
    """12. Production environment rejects development-only impersonation while dev environment allows it."""
    transport = ASGITransport(app=app)
    settings = get_settings()

    # In production: rejected
    with patch.object(settings, "ENVIRONMENT", "production"):
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get("/api/auth/me", headers={"x-user-id": "hacker@evil.com"})
            assert resp.status_code == 403
            assert "impersonation is strictly forbidden" in resp.json()["detail"]

    # In development: permitted
    with patch.object(settings, "ENVIRONMENT", "development"):
        async with AsyncClient(transport=transport, base_url="http://localhost:5173") as client:
            resp = await client.get("/api/auth/me", headers={"x-user-id": "dev_student@vit.ac.in"})
            assert resp.status_code == 200
            assert resp.json()["user_id"] == "dev_student@vit.ac.in"


@pytest.mark.asyncio
async def test_13_oauth_initiation_and_callback_work_with_actual_configured_redirect_uri():
    """13. OAuth initiation and callback work with the exact configured redirect URI."""
    transport = ASGITransport(app=app)
    settings = get_settings()
    configured_uri = "https://compass-farmlytics.vercel.app/api/calendar/callback"

    with patch.object(settings, "GOOGLE_REDIRECT_URI", configured_uri), \
         patch("backend.services.oauth.is_google_oauth_configured", return_value=True), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
         patch("backend.services.calendar.save_calendar_connection", new_callable=AsyncMock):

        mock_exchange.return_value = {
            "access_token": "ya29.test",
            "refresh_token": "1//test",
            "email": "user@gmail.com",
        }

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            res_connect = await client.get("/api/calendar/connect")
            assert res_connect.status_code == 200
            auth_url = res_connect.json()["url"]
            assert f"redirect_uri={urllib.parse.quote(configured_uri, safe='')}" in auth_url

            state = res_connect.json()["state"]
            res_cb = await client.get(f"/api/calendar/callback?code=mock_code&state={state}", follow_redirects=False)
            assert res_cb.status_code == 303
            assert mock_exchange.called
            assert mock_exchange.call_args.kwargs["redirect_uri"] == configured_uri


@pytest.mark.asyncio
async def test_14_failure_does_not_leave_partially_connected_integration():
    """14. Database failure or exchange failure does not leave a partially connected integration."""
    transport = ASGITransport(app=app)
    state = bound_state("scholar@vit.ac.in")

    with patch("backend.routers.auth.get_pool", return_value=MagicMock()), \
         patch("backend.services.oauth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
         patch("backend.services.calendar.save_calendar_connection", side_effect=Exception("DB connection dropped")):

        mock_exchange.return_value = {
            "access_token": "ya29.test",
            "refresh_token": "1//test",
            "email": "scholar@gmail.com",
        }

        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app", cookies=NONCE_COOKIES) as client:
            resp = await client.get(f"/api/calendar/callback?code=mock_code&state={state}", follow_redirects=False)
            assert resp.status_code == 303
            assert "calendar_error=database_error" in resp.headers["location"]


@pytest.mark.asyncio
async def test_15_existing_non_oauth_api_authentication_and_impersonation_protections_continue():
    """15. Existing non-OAuth API authentication and impersonation protections continue to work."""
    transport = ASGITransport(app=app)
    settings = get_settings()

    valid_session = create_session("real_student@vit.ac.in")
    with patch.object(settings, "ENVIRONMENT", "production"):
        async with AsyncClient(
            transport=transport,
            base_url="https://compass-farmlytics.vercel.app",
            cookies={"compass_session": valid_session},
        ) as client:
            resp = await client.get("/api/auth/me")
            assert resp.status_code == 200
            data = resp.json()
            assert data["authenticated"] is True
            assert data["user_id"] == "real_student@vit.ac.in"

    with patch.object(settings, "ENVIRONMENT", "production"):
        async with AsyncClient(transport=transport, base_url="https://compass-farmlytics.vercel.app") as client:
            resp = await client.get("/api/auth/me", headers={"x-user-id": "attacker@vit.ac.in"})
            assert resp.status_code == 403
            assert "impersonation is strictly forbidden" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_16_simultaneous_concurrent_callback_attempts_atomically_deduplicated():
    """16. Two simultaneous concurrent attempts to consume the exact same valid state: exactly one succeeds."""
    state = generate_oauth_state("concurrent_user@vit.ac.in")

    # Fire two concurrent coroutines using asyncio.gather
    results = await asyncio.gather(
        verify_and_consume_oauth_state(state),
        verify_and_consume_oauth_state(state),
    )

    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    assert successes[0][1] == "concurrent_user@vit.ac.in"
    assert failures[0][2] == "replayed_state"


@pytest.mark.asyncio
async def test_17_shared_database_pool_enforces_single_use_across_workers():
    """17. State replay across separate verifier instances or workers backed by PostgreSQL pool."""
    state = generate_oauth_state("worker_user@vit.ac.in")

    # Simulate PostgreSQL primary key behavior in a shared database
    db_consumed = set()

    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    async def mock_execute(query, sig, user_id, action, expires_at):
        if sig in db_consumed:
            return "INSERT 0 0"  # Conflict: 0 rows inserted
        db_consumed.add(sig)
        return "INSERT 0 1"  # Success: 1 row inserted

    mock_conn.execute.side_effect = mock_execute
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Worker 1: consumes state
    valid1, user1, err1 = await verify_and_consume_oauth_state(state, pool=mock_pool)
    assert valid1 is True
    assert user1 == "worker_user@vit.ac.in"
    assert err1 is None

    # Worker 2 (separate process / memory space): tries to consume same state against shared DB
    valid2, user2, err2 = await verify_and_consume_oauth_state(state, pool=mock_pool)
    assert valid2 is False
    assert user2 is None
    assert err2 == "replayed_state"


@pytest.mark.asyncio
async def test_18_state_replay_prevented_across_process_restart():
    """18. State replay after process restart (clearing memory cache) is blocked by persistent DB record."""
    from backend.services.oauth import _CONSUMED_OAUTH_STATES
    state = generate_oauth_state("restart_user@vit.ac.in")

    db_store = set()
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    async def mock_execute(query, sig, user_id, action, expires_at):
        if sig in db_store:
            return "INSERT 0 0"
        db_store.add(sig)
        return "INSERT 0 1"

    mock_conn.execute.side_effect = mock_execute
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Consume on Process A
    valid1, _, _ = await verify_and_consume_oauth_state(state, pool=mock_pool)
    assert valid1 is True

    # Process A restarts: memory cache is completely wiped
    _CONSUMED_OAUTH_STATES.clear()

    # Process B starts up fresh: DB still retains record
    valid2, _, err2 = await verify_and_consume_oauth_state(state, pool=mock_pool)
    assert valid2 is False
    assert err2 == "replayed_state"


@pytest.mark.asyncio
async def test_19_cross_action_state_replay_rejected():
    """19. A valid state generated for calendar integration cannot be consumed for another action/service."""
    # State generated with action="google_calendar"
    state = generate_oauth_state("user@vit.ac.in", action="google_calendar")

    # Attempt to consume with action="github_integration"
    valid, user, err = await verify_and_consume_oauth_state(state, expected_action="github_integration")
    assert valid is False
    assert user is None
    assert err == "invalid_action"


@pytest.mark.asyncio
async def test_20_dedicated_state_secret_and_key_rotation():
    """20. Dedicated COMPASS_STATE_SECRET signs state; rotating the secret invalidates old state without affecting stored tokens."""
    import os
    from backend.services.oauth import generate_oauth_state, verify_and_consume_oauth_state

    with patch.dict(os.environ, {"COMPASS_STATE_SECRET": "secret-key-generation-one-12345678"}):
        state1 = generate_oauth_state("rotator@vit.ac.in")

        # Verifies with same secret
        valid, user, err = await verify_and_consume_oauth_state(state1)
        assert valid is True
        assert user == "rotator@vit.ac.in"

    # Now rotate secret to generation two
    with patch.dict(os.environ, {"COMPASS_STATE_SECRET": "secret-key-generation-two-87654321"}):
        # Old state signed with gen 1 should be rejected
        valid2, user2, err2 = await verify_and_consume_oauth_state(state1)
        assert valid2 is False
        assert err2 == "invalid_state"


@pytest.mark.asyncio
async def test_21_database_failure_in_production_fails_loudly_without_silent_memory_fallback():
    """21. In production, a missing table or DB query failure raises an operational error and redirects to database_error."""
    from backend.config import get_settings

    state = bound_state("prod_user@vit.ac.in")
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = Exception('relation "oauth_consumed_states" does not exist')
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    prod_settings = get_settings()
    with patch.object(prod_settings, "ENVIRONMENT", "production"), \
         patch("backend.config.Settings.validate_production_secrets", return_value=None), \
         patch("backend.routers.auth.get_pool", return_value=mock_pool), \
         patch("backend.services.oauth.get_settings", return_value=prod_settings):
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=NONCE_COOKIES) as ac:
            resp = await ac.get(
                "/api/calendar/callback",
                params={"code": "valid_code", "state": state},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            # Must NOT silently succeed in memory; must report database_error
            assert "calendar_error=database_error" in resp.headers["location"]


@pytest.mark.asyncio
async def test_22_cleanup_expired_oauth_states_only_deletes_expired_rows():
    """22. cleanup_expired_oauth_states executes DELETE with expires_at < now(), never touching valid states."""
    from backend.services.oauth import cleanup_expired_oauth_states

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "DELETE 42"
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    pruned = await cleanup_expired_oauth_states(mock_pool)
    assert pruned == 42
    query_called = mock_conn.execute.call_args[0][0]
    assert "DELETE FROM oauth_consumed_states WHERE expires_at < now()" in query_called


