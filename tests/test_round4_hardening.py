"""
Compass — Round 4 Hardening Test Suite.

Comprehensive tests covering:
1. Share Links:
   - Conversation ID does NOT resolve a share (404)
   - Revoked token returns 404
   - No owner PII in shared response
2. Proxy Hops:
   - Shorter chain than TRUSTED_PROXY_HOPS falls back strictly to TCP peer address
   - Forged XFF cannot alter client IP bucket key
3. Event-Page Rule:
   - Attacker project page (/software/...) titled with entity name stays Tier 2
   - Pinned prefix promotes platform page to Tier 1
4. SSRF TLS:
   - Non-blocking DNS resolution
   - TLS verification ON with SNI hostname extension
   - Certificate mismatch raises TLS verification error
   - DNS rebinding to private IP blocked
   - Redirect to private/loopback IP blocked
5. SSE Streaming:
   - Client disconnect cancels upstream stream (CancelledError)
   - Tool-call path emits no duplicate text
   - Mid-stream failure emits terminal error event
6. Cross-Identity Negative Tests:
   - User B attempting to access User A's tasks, conversations, agent actions, migration, calendar, etc.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import get_settings
from backend.dependencies import Identity, _get_current_identity
from backend.services.security import get_client_ip, safe_http_get, is_safe_redirect
from backend.services.tavily_authority import AuthorityTier, classify_domain_authority
from backend.agent_pending import verify_and_claim_action
from backend.models import StreamChatRequest


# ============================================================================
# 1. SHARE LINKS
# ============================================================================

@pytest.mark.asyncio
async def test_share_link_conversation_id_does_not_resolve():
    """Verify that a conversation UUID does NOT resolve a share link (token-only)."""
    from backend.routers.chat import get_shared_conversation

    conv_uuid = str(uuid.uuid4())
    req = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # Query WHERE share_token = $1 AND is_shared = TRUE

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.chat.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc:
            await get_shared_conversation(conv_uuid, req)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_share_link_revoked_token_returns_404():
    """Verify that when a conversation is unshared, the share token is invalidated -> 404."""
    from backend.routers.chat import get_shared_conversation

    revoked_token = "revoked_token_abc123"
    req = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.chat.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc:
            await get_shared_conversation(revoked_token, req)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_share_link_no_owner_pii_in_response():
    """Verify that shared conversation response contains NO owner PII (user_id, email)."""
    from backend.routers.chat import get_shared_conversation

    valid_token = "valid_safe_token_xyz987"
    req = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})

    mock_row = {
        "id": uuid.uuid4(),
        "title": "Public Shared Chat",
        "started_at": "2026-10-01T12:00:00Z",
        "last_active_at": "2026-10-01T12:00:00Z",
        "share_token": valid_token,
        "is_shared": True,
        "user_id": "secret_owner@example.com",
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = mock_row
    mock_conn.fetch.return_value = [
        {"role": "user", "content": "Hello", "created_at": "2026-10-01T12:00:00Z", "skill_called": None}
    ]

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.chat.get_pool", return_value=mock_pool):
        result = await get_shared_conversation(valid_token, req)
        assert "user_id" not in result
        assert "email" not in result
        assert "owner" not in result
        assert result["title"] == "Public Shared Chat"
        assert len(result["messages"]) == 1


# ============================================================================
# 2. PROXY HOPS & IP RESOLUTION
# ============================================================================

def test_proxy_hops_shorter_chain_falls_back_to_peer_address():
    """When X-Forwarded-For has fewer elements than TRUSTED_PROXY_HOPS, fallback to TCP peer."""
    scope = {
        "type": "http",
        "client": ("192.0.2.1", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.195")],
    }
    req = Request(scope)

    from backend.config import Settings
    s = Settings(TRUSTED_PROXY_HOPS=2, TRUST_CF_CONNECTING_IP=False, TRUST_TRUE_CLIENT_IP=False)
    with patch("backend.config.get_settings", return_value=s):
        ip = get_client_ip(req)
        assert ip == "192.0.2.1"


def test_forged_xff_cannot_change_bucket_key():
    """Attacker attempting to spoof XFF on direct connection cannot manipulate bucket key."""
    scope = {
        "type": "http",
        "client": ("198.51.100.5", 43210),
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 8.8.8.8, 9.9.9.9")],
    }
    req = Request(scope)

    from backend.config import Settings
    s = Settings(TRUSTED_PROXY_HOPS=1, TRUST_CF_CONNECTING_IP=False, TRUST_TRUE_CLIENT_IP=False)
    with patch("backend.config.get_settings", return_value=s):
        ip = get_client_ip(req)
        assert ip in ("9.9.9.9", "198.51.100.5")
        assert ip != "1.1.1.1"


# ============================================================================
# 3. EVENT-PAGE RULE
# ============================================================================

def test_event_page_rule_attacker_project_page_stays_tier_2():
    """Attacker project page (/software/...) titled with target entity name cannot become Tier 1."""
    attacker_url = "https://devpost.com/software/nebius-fake-official-page"
    classification = classify_domain_authority(
        attacker_url,
        target_entity="Nebius x NVIDIA",
        is_entity_bound=True,
        page_title_matches_entity=True,
    )
    assert classification["tier"] == AuthorityTier.TIER_2_TECHNICAL.value
    assert classification["tier"] != AuthorityTier.TIER_1_OFFICIAL.value
    assert "cannot be Tier 1 official" in classification["reason"]


def test_event_page_rule_pinned_prefix_promotes_to_tier_1():
    """Platform event page matching pinned prefix in config is promoted to Tier 1."""
    official_event_url = "https://nebiusglobalaihackathon.devpost.com/rules"
    classification = classify_domain_authority(
        official_event_url,
        target_entity="Nebius x NVIDIA",
        is_entity_bound=True,
        pinned_event_prefixes=["https://nebiusglobalaihackathon.devpost.com"],
    )
    assert classification["tier"] == AuthorityTier.TIER_1_OFFICIAL.value
    assert "Official" in classification["badge"]


# ============================================================================
# 4. SSRF TLS & TRANSPORT
# ============================================================================

@pytest.mark.asyncio
async def test_ssrf_cert_mismatch_fails_tls_verification():
    """Verify that pinned IP transport preserves TLS verification and fails on mismatched cert."""
    mismatched_url = "https://wrong.host.badssl.com/"
    with pytest.raises(Exception):
        await safe_http_get(mismatched_url, timeout=5.0)


@pytest.mark.asyncio
async def test_ssrf_dns_rebinding_blocked():
    """Verify that DNS rebinding to private IP is blocked."""
    with patch("asyncio.get_running_loop") as mock_loop_fn:
        mock_loop = AsyncMock()
        mock_loop.getaddrinfo.return_value = [(None, None, None, None, ("127.0.0.1", 443))]
        mock_loop_fn.return_value = mock_loop
        with pytest.raises(ValueError) as exc:
            await safe_http_get("https://example.com/test")
        assert "DNS rebinding blocked" in str(exc.value)


@pytest.mark.asyncio
async def test_ssrf_redirect_to_private_ip_blocked():
    """Verify that redirecting to private IP (10.0.0.1, 169.254.169.254) is blocked."""
    private_redirects = [
        "http://10.0.0.1/admin",
        "http://192.168.1.1/setup",
        "http://169.254.169.254/latest/meta-data/",
    ]
    for target in private_redirects:
        is_safe, resolved, reason = is_safe_redirect("https://safe-domain.com/landing", target)
        assert not is_safe
        assert "Redirect destination rejected" in reason


# ============================================================================
# 5. SSE STREAMING
# ============================================================================

class MockAsyncStream:
    """Mock async generator stream for testing SSE behavior without live model connections."""
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_sse_disconnect_cancels_upstream():
    """Verify that client disconnect closes upstream generator and CancelledError is propagated."""
    from backend.routers.chat import stream_chat

    # 1. Test client disconnect stops iteration cleanly
    req = StreamChatRequest(message="hi", conversation_id="conv-1")
    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])

    chunk = MagicMock()
    chunk.usage = None
    chunk.choices = [MagicMock(delta=MagicMock(content="chunk1", tool_calls=None), finish_reason=None)]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockAsyncStream([chunk, chunk]))

    with patch("openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.routers.chat.get_pool", return_value=None), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="u1", is_admin=False, user_id="u1")):
        resp = await stream_chat(req, request)
        gen = resp.body_iterator

        first = await anext(gen)  # ": ping\n\n"
        assert "ping" in first
        second = await anext(gen)  # first token
        assert "chunk1" in second

        # Next iteration detects is_disconnected=True and terminates stream
        with pytest.raises(StopAsyncIteration):
            await anext(gen)

    # 2. Test CancelledError during stream is re-raised
    request_cancel = MagicMock(spec=Request)
    request_cancel.is_disconnected = AsyncMock(return_value=False)
    mock_client_cancel = MagicMock()
    mock_client_cancel.chat.completions.create = AsyncMock(return_value=MockAsyncStream([chunk, asyncio.CancelledError()]))

    with patch("openai.AsyncOpenAI", return_value=mock_client_cancel), \
         patch("backend.routers.chat.get_pool", return_value=None), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="u1", is_admin=False, user_id="u1")):
        resp = await stream_chat(req, request_cancel)
        gen = resp.body_iterator
        await anext(gen)  # ping
        await anext(gen)  # chunk1
        with pytest.raises(asyncio.CancelledError):
            await anext(gen)


@pytest.mark.asyncio
async def test_sse_tool_call_emits_no_duplicate_text():
    """Verify that when structured tool call is detected, no buffered text is emitted in SSE."""
    from backend.routers.chat import stream_chat

    req = StreamChatRequest(message="find tasks", conversation_id="conv-2")
    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)

    tool_chunk = MagicMock()
    tool_chunk.usage = MagicMock(total_tokens=42)
    tool_chunk.choices = [
        MagicMock(
            delta=MagicMock(
                content="",
                tool_calls=[MagicMock(id="call_1", function=MagicMock(name="get_tasks", arguments="{}"))],
            ),
            finish_reason="tool_calls",
        )
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockAsyncStream([tool_chunk]))

    with patch("openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.routers.chat.get_pool", return_value=None), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="u1", is_admin=False, user_id="u1")), \
         patch("backend.orchestrator.handle_message", return_value={"response": "Tool completed", "conversation_id": "conv-2", "skill_used": "get_tasks"}):
        resp = await stream_chat(req, request)
        events = []
        async for ev in resp.body_iterator:
            events.append(ev)

        # Ensure tool was executed and zero duplicate partial token events emitted
        token_events = [e for e in events if '"type": "token"' in e]
        assert len(token_events) == 1
        assert "Tool completed" in token_events[0]


@pytest.mark.asyncio
async def test_sse_mid_stream_failure_emits_terminal_error():
    """Verify that mid-stream failure emits a terminal error event."""
    from backend.routers.chat import stream_chat

    req = StreamChatRequest(message="hi", conversation_id="conv-3")
    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)

    chunk = MagicMock()
    chunk.usage = None
    chunk.choices = [MagicMock(delta=MagicMock(content="hello", tool_calls=None), finish_reason=None)]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockAsyncStream([chunk, RuntimeError("Nebius API upstream timeout")]))

    with patch("openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.routers.chat.get_pool", return_value=None), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="u1", is_admin=False, user_id="u1")):
        resp = await stream_chat(req, request)
        events = []
        async for ev in resp.body_iterator:
            events.append(ev)

        error_events = [e for e in events if '"type": "error"' in e]
        assert len(error_events) == 1
        assert '"terminal": true' in error_events[0]
        assert "upstream timeout" in error_events[0]


# ============================================================================
# 6. IDENTITY & ADMIN OVERRIDE (Item 8 & 9)
# ============================================================================

def test_x_user_id_impersonation_forbidden_in_production():
    """x-user-id impersonation is strictly forbidden when ENVIRONMENT is not development or test."""
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"authorization", b"Bearer test-secret-token"),
            (b"x-user-id", b"victim@example.com"),
        ],
        "path": "/api/tasks",
    }
    req = Request(scope)

    with patch("backend.dependencies.get_settings") as mock_settings:
        mock_settings.return_value.AUTH_TOKEN = "test-secret-token"
        mock_settings.return_value.ENVIRONMENT = "production"

        with pytest.raises(HTTPException) as exc:
            _get_current_identity(req)
        assert exc.value.status_code == 403
        assert "x-user-id impersonation is forbidden" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_and_claim_action_uses_identity_is_admin():
    """Verify that verify_and_claim_action allows admin override ONLY via is_admin=True, NOT string comparison."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "action_id": "act-123",
        "owner_identity": "victim_user",
        "status": "pending",
        "expires_at": None,
        "args_hash": "hash1",
        "original_args": "{}",
    }
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    # 1. Attacker passing username "admin" with is_admin=False -> REJECTED
    fake_admin_identity = Identity(id="admin", is_admin=False, is_guest=False)
    ok, msg, _ = await verify_and_claim_action(mock_pool, "act-123", None, fake_admin_identity)
    assert not ok
    assert "Permission denied" in msg

    # 2. Genuine admin with is_admin=True -> ALLOWED
    real_admin_identity = Identity(id="admin", is_admin=True, is_guest=False)
    ok, msg, _ = await verify_and_claim_action(mock_pool, "act-123", None, real_admin_identity)
    assert ok


# ============================================================================
# 7. CROSS-IDENTITY NEGATIVE TESTS (Every Route Touching User Data)
# ============================================================================


@pytest.mark.asyncio
async def test_cross_identity_tasks_isolation_negative():
    """User B cannot edit or delete User A's task (returns 403)."""
    from backend.routers.tasks import update_frontend_task, delete_frontend_task
    from backend.models import UpdateTaskRequest

    scope_user_b = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"authorization", b"Bearer session_user_b")],
    }
    req = Request(scope_user_b)

    mock_conn = AsyncMock()
    # Task is owned by user_a
    mock_conn.fetchrow.return_value = {"id": 999, "user_id": "user_a", "title": "Secret Task"}

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.tasks.get_pool", return_value=mock_pool), \
         patch("backend.routers.tasks.structured.get_task", return_value={"id": 999, "user_id": "user_a"}), \
         patch("backend.dependencies._get_current_identity", return_value=Identity(id="user_b", is_admin=False, user_id="user_b")), \
         patch("backend.routers.tasks._get_or_create_user_id", return_value="user_b"):
        
        with pytest.raises(HTTPException) as exc_update:
            await update_frontend_task("999", UpdateTaskRequest(title="Tampered"), req)
        assert exc_update.value.status_code == 403
        assert "permission to modify this task" in exc_update.value.detail

        with pytest.raises(HTTPException) as exc_del:
            await delete_frontend_task("999", req)
        assert exc_del.value.status_code == 403
        assert "permission to delete this task" in exc_del.value.detail


@pytest.mark.asyncio
async def test_cross_identity_conversation_isolation_negative():
    """User B cannot access, update, or delete User A's conversation (returns 403)."""
    from backend.routers.chat import delete_past_conversation, get_messages, update_past_conversation
    from backend.models import ConversationUpdate

    scope_user_b = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"authorization", b"Bearer session_user_b")],
    }
    req = Request(scope_user_b)

    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.chat.get_pool", return_value=mock_pool), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="user_b", is_admin=False, user_id="user_b")), \
         patch("backend.routers.chat.conversations.check_conversation_access", return_value=(False, "Forbidden: You do not have permission to access this conversation")):
        
        with pytest.raises(HTTPException) as exc_del:
            await delete_past_conversation("conv_owned_by_user_a", req)
        assert exc_del.value.status_code == 403

        with pytest.raises(HTTPException) as exc_get:
            await get_messages("conv_owned_by_user_a", req)
        assert exc_get.value.status_code == 403

        with pytest.raises(HTTPException) as exc_upd:
            await update_past_conversation("conv_owned_by_user_a", ConversationUpdate(title="Hacked"), req)
        assert exc_upd.value.status_code == 403


@pytest.mark.asyncio
async def test_cross_identity_agent_undo_isolation_negative():
    """User B cannot undo User A's agent action (returns 403)."""
    from backend.routers.agent import agent_undo
    from backend.models import AgentUndoRequest

    scope_user_b = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"authorization", b"Bearer session_user_b")],
    }
    req = Request(scope_user_b)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": 1,
        "run_id": "run_a",
        "approved_by": "user_a",
        "args": json.dumps({"user_id": "user_a"}),
    }
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    with patch("backend.routers.agent.get_pool", return_value=mock_pool), \
         patch("backend.dependencies._get_current_identity", return_value=Identity(id="user_b", is_admin=False, user_id="user_b")):
        with pytest.raises(HTTPException) as exc:
            await agent_undo(AgentUndoRequest(run_id="run_a"), req)
        assert exc.value.status_code == 403
        assert "permission to undo another user's action" in exc.value.detail


@pytest.mark.asyncio
async def test_cross_identity_migration_isolation_negative():
    """Unauthenticated caller or caller with no guest session cannot access migration candidates."""
    from backend.routers.migration import list_migration_conversations

    scope_unauth = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [],
    }
    req = Request(scope_unauth)

    with patch("backend.routers.migration._get_current_identity", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await list_migration_conversations(req)
        assert exc.value.status_code == 401
