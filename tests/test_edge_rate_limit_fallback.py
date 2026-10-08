"""
Tests for Edge / Proxy IP resolution and safe fallback rate limiting.

Verifies:
1. When EDGE_HMAC_SECRET is unset or edge signature is missing/invalid,
   is_edge_ip_trusted is False. Multiple users behind the same Vercel proxy hop
   are isolated by identity rather than exhausting a single shared IP bucket.
2. When a valid cryptographic edge signature is provided, the signed client IP
   is verified, trusted, and used for strict IP enforcement.
"""

import hashlib
import hmac
import time
import pytest
from starlette.requests import Request

from backend.services.security import get_client_ip, is_edge_ip_trusted
from backend.services.rate_limiter import enforce_rate_limit, _MEM_BUCKETS
from backend.dependencies import Identity



def make_request(headers: dict[str, str], client_host: str = "127.0.0.1") -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": raw_headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_edge_rate_limit_with_and_without_valid_signature(monkeypatch):
    test_secret = "test_edge_secret_for_simulation_32chars!"
    from backend.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_HMAC_SECRET", test_secret)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)

    # Clear in-memory rate limit buckets
    _MEM_BUCKETS.clear()

    # ------------------------------------------------------------------------
    # SCENARIO A: Vercel path WITHOUT valid signature (EDGE_HMAC_SECRET unset / bad signature)
    # ------------------------------------------------------------------------
    # Two different Vercel users (guest_alice and guest_bob) arrive via Vercel proxy (egress IP: 76.76.21.21)
    proxy_headers_no_sig = {
        "x-forwarded-for": "198.51.100.55, 76.76.21.21",  # client_ip, vercel_edge_ip
    }
    req_alice = make_request(proxy_headers_no_sig)
    req_bob = make_request(proxy_headers_no_sig)

    # Check client IP resolution and trust
    assert get_client_ip(req_alice) == "76.76.21.21"
    assert is_edge_ip_trusted(req_alice) is False

    # Attach mock identities
    req_alice.state.identity = Identity(id="guest_alice", is_guest=True, guest_id="guest_alice")
    req_bob.state.identity = Identity(id="guest_bob", is_guest=True, guest_id="guest_bob")

    # Alice sends 2 requests (capacity=2.0, refill_rate near zero so WAN delay does not refill)
    await enforce_rate_limit(req_alice, action="test_action", identity_capacity=2.0, identity_refill_per_sec=0.0001, ip_capacity=2.0)
    await enforce_rate_limit(req_alice, action="test_action", identity_capacity=2.0, identity_refill_per_sec=0.0001, ip_capacity=2.0)

    # Alice's 3rd request should fail with 429 for identity
    with pytest.raises(Exception) as excinfo:
        await enforce_rate_limit(req_alice, action="test_action", identity_capacity=2.0, identity_refill_per_sec=0.0001, ip_capacity=2.0)
    assert excinfo.value.status_code == 429
    assert "identity" in excinfo.value.detail.lower()

    # Bob (different user behind the same Vercel proxy) MUST NOT be blocked by Alice's bucket!
    # Because identity is the primary key when IP is untrusted:
    await enforce_rate_limit(req_bob, action="test_action", identity_capacity=2.0, identity_refill_per_sec=0.0001, ip_capacity=2.0)
    # Bob succeeded without getting 429!

    # ------------------------------------------------------------------------
    # SCENARIO B: Vercel path WITH valid signature from Edge Middleware
    # ------------------------------------------------------------------------
    real_client_ip = "203.0.113.199"
    ts_now = str(int(time.time()))
    payload = f"{real_client_ip}|{ts_now}"
    valid_sig = hmac.new(test_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    edge_sig_header = f"{real_client_ip}|{ts_now}|{valid_sig}"

    proxy_headers_with_sig = {
        "x-forwarded-for": "203.0.113.199, 76.76.21.21",
        "x-compass-edge-sig": edge_sig_header,
    }
    req_signed = make_request(proxy_headers_with_sig)

    # With valid signature: client IP is trusted and matches real_client_ip
    assert is_edge_ip_trusted(req_signed) is True
    assert get_client_ip(req_signed) == real_client_ip
