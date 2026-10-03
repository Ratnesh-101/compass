"""
Compass — Security Hardening Regression Tests.

Verifies:
  - Fail-closed production secrets (AUTH_TOKEN, TOKEN_ENCRYPTION_KEY).
  - Constant-time Bearer token verification.
  - SSRF protection rejecting loopback, RFC 1918, cloud metadata, and unsafe schemes.
  - Safe client IP extraction for rate limiters.
  - IDOR protection on task update and deletion.
  - Confirmation gate and CORS origin enforcement.
"""

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from httpx import AsyncClient

from backend.config import Settings
from backend.services.security import is_safe_url, get_client_ip
from backend.dependencies import verify_token
from backend.skills.handlers.web import handle_ingest_url


# ===========================================================================
# 1. Secret Management & Fail-Closed Production Tests
# ===========================================================================

def test_production_fail_closed_with_dev_auth_token():
    """In production mode, default 'dev-token' must be rejected with ValueError."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        AUTH_TOKEN="dev-token",
        TOKEN_ENCRYPTION_KEY="custom-secure-key-for-prod-32bytes!",
    )
    with pytest.raises(ValueError, match="CRITICAL SECURITY CONFIGURATION ERROR: AUTH_TOKEN"):
        prod_settings.validate_production_secrets()


def test_production_fail_closed_with_empty_auth_token():
    """In production mode, empty AUTH_TOKEN must be rejected."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        AUTH_TOKEN="",
        TOKEN_ENCRYPTION_KEY="custom-secure-key-for-prod-32bytes!",
    )
    with pytest.raises(ValueError, match="CRITICAL SECURITY CONFIGURATION ERROR: AUTH_TOKEN"):
        prod_settings.validate_production_secrets()


def test_production_fail_closed_with_default_encryption_key():
    """In production mode, default TOKEN_ENCRYPTION_KEY must be rejected."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        AUTH_TOKEN="real-production-secret-token-12345",
        TOKEN_ENCRYPTION_KEY="compass_secure_local_dev_token_encryption_key_32bytes!",
    )
    with pytest.raises(ValueError, match="CRITICAL SECURITY CONFIGURATION ERROR: TOKEN_ENCRYPTION_KEY"):
        prod_settings.validate_production_secrets()


def test_development_allows_dev_tokens():
    """In development mode, default development credentials do not raise errors."""
    dev_settings = Settings(
        ENVIRONMENT="development",
        AUTH_TOKEN="dev-token",
        TOKEN_ENCRYPTION_KEY="compass_secure_local_dev_token_encryption_key_32bytes!",
    )
    # Should complete cleanly without raising
    dev_settings.validate_production_secrets()
    assert not dev_settings.is_production()


# ===========================================================================
# 2. SSRF (Server-Side Request Forgery) Validation Tests
# ===========================================================================

@pytest.mark.parametrize(
    "unsafe_url,expected_blocked",
    [
        ("http://127.0.0.1:8000/api/admin/usage", True),
        ("http://localhost:5432", True),
        ("http://169.254.169.254/latest/meta-data/", True),
        ("http://10.0.0.1/internal-dashboard", True),
        ("http://192.168.1.1/admin", True),
        ("http://172.16.0.5/secrets", True),
        ("http://0.0.0.0:8000", True),
        ("ftp://ftp.example.com/file.txt", True),
        ("file:///etc/passwd", True),
        ("gopher://127.0.0.1:70", True),
    ],
)
def test_ssrf_validator_blocks_internal_targets(unsafe_url: str, expected_blocked: bool):
    """is_safe_url must block internal addresses, cloud metadata, and unsupported schemes."""
    is_safe, reason = is_safe_url(unsafe_url)
    assert is_safe is not expected_blocked
    assert len(reason) > 0


def test_ssrf_validator_allows_public_urls():
    """is_safe_url must allow standard public web URLs."""
    safe_urls = [
        "https://devpost.com/hackathons",
        "https://api.github.com/repos",
        "http://example.com/index.html",
    ]
    for url in safe_urls:
        is_safe, reason = is_safe_url(url)
        assert is_safe is True, f"Expected {url} to be safe, but got reason: {reason}"


@pytest.mark.asyncio
async def test_handle_ingest_url_blocks_ssrf_payload():
    """handle_ingest_url handler must reject SSRF target URLs before external calls."""
    ssrf_payload = {"url": "http://169.254.169.254/latest/meta-data/", "domain": "general"}
    result = await handle_ingest_url(ssrf_payload, pool=None)
    assert result["success"] is False
    assert "SSRF blocked" in result["error"]


# ===========================================================================
# 3. Client IP Extraction & Spoofing Resistance
# ===========================================================================

def test_safe_client_ip_prefers_direct_host_when_no_proxy():
    """get_client_ip returns request.client.host when no proxy headers are present."""
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client.host = "203.0.113.42"
    ip = get_client_ip(mock_request)
    assert ip == "203.0.113.42"


def test_safe_client_ip_handles_forwarded_for(monkeypatch):
    """get_client_ip extracts the trusted rightmost client IP from proxy headers to prevent spoofing."""
    mock_request = MagicMock()
    mock_request.headers = {"x-forwarded-for": "spoofed-ip, 198.51.100.15"}
    mock_request.client.host = "10.0.0.1"
    ip = get_client_ip(mock_request)
    assert ip == "198.51.100.15"

    # Cloudflare connecting IP is ignored when TRUST_CF_CONNECTING_IP is False
    from backend.config import get_settings
    monkeypatch.setattr(get_settings(), "TRUST_CF_CONNECTING_IP", False)
    mock_request.headers = {"cf-connecting-ip": "203.0.113.88", "x-forwarded-for": "spoofed-ip, 198.51.100.15"}
    assert get_client_ip(mock_request) == "198.51.100.15"

    # Cloudflare connecting IP is honored when TRUST_CF_CONNECTING_IP is True
    monkeypatch.setattr(get_settings(), "TRUST_CF_CONNECTING_IP", True)
    assert get_client_ip(mock_request) == "203.0.113.88"


# ===========================================================================
# 4. Insecure Direct Object Reference (IDOR) Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_task_idor_user_cannot_modify_other_user_task(client: AsyncClient, monkeypatch):
    """A user cannot update or delete another user's task without ownership."""
    from backend.memory import structured

    from contextlib import asynccontextmanager
    import backend.routers.tasks as tasks_router

    class MockConn:
        pass

    class MockPool:
        @asynccontextmanager
        async def acquire(self):
            yield MockConn()

    async def mock_get_pool():
        return MockPool()

    monkeypatch.setattr(tasks_router, "get_pool", mock_get_pool)

    mock_alice_task = {
        "id": 999,
        "title": "Alice Private Project",
        "domain": "code",
        "priority": "high",
        "status": "open",
        "notes": "secret notes",
        "due_date": None,
        "user_id": "alice",
        "project": None,
        "duration_minutes": 60,
        "scheduled_start": None,
        "scheduled_end": None,
        "is_fixed": False,
        "created_at": None,
        "updated_at": None,
    }

    async def mock_get_task(conn, task_id):
        if task_id == 999:
            return mock_alice_task
        return None

    monkeypatch.setattr(structured, "get_task", mock_get_task)

    from backend.routers.auth import create_session
    bob_cookie = {"compass_session": create_session("bob")}
    alice_cookie = {"compass_session": create_session("alice")}

    # 1. User 'bob' attempts to PATCH Alice's task -> must be 403 Forbidden
    patch_resp = await client.patch(
        "/api/tasks/999",
        cookies=bob_cookie,
        json={"title": "Hacked Title by Bob"},
    )
    assert patch_resp.status_code == 403
    assert "Forbidden" in patch_resp.json()["detail"]

    # 2. User 'bob' attempts to DELETE Alice's task -> must be 403 Forbidden
    delete_resp = await client.delete(
        "/api/tasks/999",
        cookies=bob_cookie,
    )
    assert delete_resp.status_code == 403
    assert "Forbidden" in delete_resp.json()["detail"]

    # 3. User 'alice' (owner) can modify her task
    async def mock_update_task(conn, task_id, **kwargs):
        updated = dict(mock_alice_task)
        updated.update(kwargs)
        return updated

    monkeypatch.setattr(structured, "update_task", mock_update_task)
    alice_patch_resp = await client.patch(
        "/api/tasks/999",
        cookies=alice_cookie,
        json={"title": "Alice Updated Project"},
    )
    assert alice_patch_resp.status_code == 200


# ===========================================================================
# 5. CORS Header Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_cors_disallows_arbitrary_untrusted_origin(client: AsyncClient):
    """OPTIONS request with an untrusted origin should not receive Access-Control-Allow-Origin."""
    headers = {
        "Origin": "https://malicious-attacker-site.com",
        "Access-Control-Request-Method": "GET",
    }
    resp = await client.options("/tasks", headers=headers)
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin != "https://malicious-attacker-site.com"
    assert allow_origin != "*"


# ===========================================================================
# 6. Unowned Task & Cross-Guest Isolation Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_unowned_task_modification_rejected_for_non_admin(client: AsyncClient, monkeypatch):
    """Legacy or unowned system tasks (user_id=None) cannot be modified or deleted by non-admin callers."""
    from contextlib import asynccontextmanager
    from backend.memory import structured
    import backend.routers.tasks as tasks_router

    class MockConn:
        pass

    class MockPool:
        @asynccontextmanager
        async def acquire(self):
            yield MockConn()

    async def mock_get_pool():
        return MockPool()

    monkeypatch.setattr(tasks_router, "get_pool", mock_get_pool)

    mock_unowned_task = {
        "id": 1001,
        "title": "Unowned System Milestone",
        "domain": "general",
        "priority": "medium",
        "status": "open",
        "notes": None,
        "due_date": None,
        "user_id": None,  # Unowned
        "project": None,
        "duration_minutes": 60,
        "scheduled_start": None,
        "scheduled_end": None,
        "is_fixed": False,
        "created_at": None,
        "updated_at": None,
    }

    async def mock_get_task(conn, task_id):
        if task_id == 1001:
            return mock_unowned_task
        return None

    monkeypatch.setattr(structured, "get_task", mock_get_task)

    # 1. Non-admin user attempts to patch unowned task -> 403 Forbidden
    patch_resp = await client.patch(
        "/api/tasks/1001",
        headers={"x-user-id": "guest_attacker"},
        json={"title": "Hijacked Task"},
    )
    assert patch_resp.status_code == 403
    assert "Unowned tasks can only be modified by an administrator" in patch_resp.json()["detail"]

    # 2. Non-admin user attempts to delete unowned task -> 403 Forbidden
    delete_resp = await client.delete(
        "/api/tasks/1001",
        headers={"x-user-id": "guest_attacker"},
    )
    assert delete_resp.status_code == 403
    assert "Unowned tasks can only be deleted by an administrator" in delete_resp.json()["detail"]


# ===========================================================================
# 7. Confirmation Gate Replay & Action Integrity Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_agent_confirm_proposal_integrity_and_replay_protection(client: AsyncClient, monkeypatch):
    """Confirmation requires Bearer auth, validates proposal matching, and rejects replay."""
    from backend.config import get_settings
    settings = get_settings()
    auth_header = {"Authorization": f"Bearer {settings.AUTH_TOKEN or 'dev-token'}"}

    # 1. Unauthenticated confirmation is rejected with 401
    unauth_resp = await client.post(
        "/api/agent/confirm",
        json={"run_id": "run_123", "actions": [{"tool": "delete_task", "args": {"task_id": 42}}]},
    )
    assert unauth_resp.status_code == 401

    # Mock get_agent_run to simulate a run that already completed (empty pending_actions)
    import backend.routers.agent as agent_router

    class MockPool:
        pass

    async def mock_get_pool():
        return MockPool()

    monkeypatch.setattr(agent_router, "get_pool", mock_get_pool)

    async def mock_get_completed_run(pool, run_id):
        return {
            "id": run_id,
            "goal": "Test goal",
            "pending_actions": [],  # No pending actions (already executed or none proposed)
            "steps": [],
            "messages": [],
        }

    monkeypatch.setattr("backend.agent.get_agent_run", mock_get_completed_run)

    # 2. Attempting to confirm a run with no pending proposals must be rejected (replay blocked)
    replay_resp = await client.post(
        "/api/agent/confirm",
        headers=auth_header,
        json={"run_id": "run_123", "actions": [{"tool": "delete_task", "args": {"task_id": 42}}]},
    )
    assert replay_resp.status_code == 400
    assert "replay rejected" in replay_resp.json()["detail"]

    # 3. Client attempts to confirm an unproposed action (tampering attempt) -> must be rejected
    async def mock_get_pending_run(pool, run_id):
        return {
            "id": run_id,
            "goal": "Test goal",
            "pending_actions": [{"tool": "add_task", "args": {"title": "Legit Task"}}],
            "steps": [],
            "messages": [],
        }

    monkeypatch.setattr("backend.agent.get_agent_run", mock_get_pending_run)

    tamper_resp = await client.post(
        "/api/agent/confirm",
        headers=auth_header,
        json={"run_id": "run_123", "actions": [{"tool": "delete_task", "args": {"task_id": 99}}]},
    )
    assert tamper_resp.status_code == 400
    assert "does not match any pending proposal" in tamper_resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_undo_replay_protection(client: AsyncClient, monkeypatch):
    """Undo rejects unauthenticated callers and blocks replaying already-reverted actions."""
    from backend.config import get_settings
    settings = get_settings()
    auth_header = {"Authorization": f"Bearer {settings.AUTH_TOKEN or 'dev-token'}"}

    # 1. Unauthenticated undo is rejected with 401
    unauth_resp = await client.post("/api/agent/undo", json={"run_id": "test_run"})
    assert unauth_resp.status_code == 401

    # 2. Mock undo_last_agent_action returning already reverted
    async def mock_undo_already_reverted(pool, run_id=None, audit_log_id=None):
        return {"status": "error", "message": f"Action #{audit_log_id or 1} has already been reverted."}

    import backend.routers.agent as agent_router
    class MockPool:
        pass
    async def mock_get_pool():
        return MockPool()
    monkeypatch.setattr(agent_router, "get_pool", mock_get_pool)
    monkeypatch.setattr("backend.agent.undo_last_agent_action", mock_undo_already_reverted)

    revert_resp = await client.post(
        "/api/agent/undo",
        headers=auth_header,
        json={"audit_log_id": 42},
    )
    assert revert_resp.status_code == 200
    assert revert_resp.json()["status"] == "error"
    assert "already been reverted" in revert_resp.json()["message"]


# ===========================================================================
# 8. SSRF IPv6 & Safe Redirect Validation Tests
# ===========================================================================

@pytest.mark.parametrize(
    "ipv6_url",
    [
        "http://[::1]:8080/secret",
        "http://[fc00::1]/admin",
        "http://[fe80::1]/metadata",
        "http://[::ffff:127.0.0.1]:8000/internal",
    ],
)
def test_ssrf_validator_blocks_internal_ipv6(ipv6_url):
    """Validate that internal, loopback, and IPv4-mapped IPv6 targets are blocked."""
    safe, reason = is_safe_url(ipv6_url)
    assert not safe
    assert "forbidden" in reason.lower() or "blocked" in reason.lower() or "private" in reason.lower()


def test_ssrf_safe_redirect_blocks_internal_destinations():
    """Redirect validator must resolve relative and absolute redirects and reject internal targets."""
    from backend.services.security import is_safe_redirect

    # Valid external redirect passes
    safe, target, reason = is_safe_redirect("https://example.com/start", "/docs/api")
    assert safe
    assert target == "https://example.com/docs/api"

    # Malicious redirect to loopback fails
    safe, target, reason = is_safe_redirect("https://example.com/start", "http://127.0.0.1:8000/api/admin")
    assert not safe
    assert "Redirect destination rejected" in reason

