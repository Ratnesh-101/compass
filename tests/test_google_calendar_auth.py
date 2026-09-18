"""
Compass — Google OAuth & Google Calendar Event Synchronization Tests.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.oauth import (
    generate_google_oauth_url,
    encrypt_token,
    decrypt_token,
    exchange_code_for_tokens,
    GOOGLE_OAUTH_SCOPE_STRING,
)
from backend.services.calendar import (
    create_google_calendar_event,
    link_calendar_event,
    sync_all_tasks_to_google_calendar,
    get_calendar_connection_status,
)


def test_google_oauth_url_generation_includes_calendar_and_user_scopes():
    """Verify that Google OAuth URL requests write permissions for calendar and user info."""
    url = generate_google_oauth_url(
        redirect_uri="http://localhost:8000/api/calendar/callback",
        state="test-state-token",
        login_hint="user@gmail.com",
    )
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "calendar.events" in url
    assert "calendar.readonly" in url
    assert "userinfo.email" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fcalendar%2Fcallback" in url
    assert "login_hint=user%40gmail.com" in url


def test_token_encryption_and_decryption():
    """Verify HMAC-authenticated encryption and decryption roundtrip."""
    secret_token = "ya29.a0AfH6SMD_real_live_google_access_token_12345"
    enc = encrypt_token(secret_token)
    assert enc.startswith("enc:")
    assert enc != secret_token

    dec = decrypt_token(enc)
    assert dec == secret_token

    # Tampered token fails decryption gracefully
    tampered = enc[:-4] + "ABCD"
    assert decrypt_token(tampered) == ""


@pytest.mark.asyncio
async def test_simulated_token_exchange():
    """Verify fallback token exchange provides user profile for demo mode."""
    tokens = await exchange_code_for_tokens("mock_code")
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert "scholar.authenticated@gmail.com" in tokens["email"]
    assert "Compass Scholar" in tokens["name"]


@pytest.mark.asyncio
async def test_create_google_calendar_event_simulated():
    """Verify simulated event creation generates an event ID and calendar link."""
    res = await create_google_calendar_event(
        access_token="mock_token_123",
        title="Ship Nemotron Feature",
        start_iso="2026-09-18T10:00:00Z",
        end_iso="2026-09-18T11:00:00Z",
        domain="hackathon",
        priority="high",
    )
    assert res["status"] == "confirmed"
    assert "id" in res
    assert "calendar.google.com" in res["htmlLink"]


@pytest.mark.asyncio
async def test_link_calendar_event_persists_link():
    """Verify link_calendar_event creates the event and links task in DB."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    res = await link_calendar_event(
        task_id=42,
        start_dt="2026-09-18T14:00:00Z",
        end_dt="2026-09-18T15:00:00Z",
        title="Benchmark GPU Memory",
        pool=mock_pool,
        user_id="scholar@gmail.com",
        domain="code",
    )
    assert res["status"] == "synced"
    assert res["task_id"] == 42
    assert "google_event_id" in res
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_sync_all_tasks_to_google_calendar():
    """Verify sync_all_tasks_to_google_calendar iterates scheduled tasks."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    mock_conn.fetch.return_value = [
        {
            "id": 1,
            "title": "Review RISC-V Pipeline",
            "domain": "coursework",
            "priority": "high",
            "notes": "Chapter 4",
            "scheduled_start": datetime.now(timezone.utc),
            "scheduled_end": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        {
            "id": 2,
            "title": "Hackathon Submission Video",
            "domain": "hackathon",
            "priority": "urgent",
            "notes": "3 min demo",
            "scheduled_start": datetime.now(timezone.utc) + timedelta(hours=2),
            "scheduled_end": datetime.now(timezone.utc) + timedelta(hours=3),
        }
    ]

    result = await sync_all_tasks_to_google_calendar(mock_pool, user_id="scholar@gmail.com")
    assert result["success"] is True
    assert result["count"] == 2
    assert len(result["events"]) == 2
    assert result["user_id"] == "scholar@gmail.com"
