"""
DNS-rebinding regression tests for the opportunity verifier's outbound fetch.

The verifier used to validate a URL (one DNS lookup) and then let httpx resolve the hostname again
at connect time, so a rebinding hostname could be public at check time and internal at connect time.
safe_http_get_with_url resolves once, validates, and connects to that exact address.
No test here touches the real network or real DNS.
"""

import asyncio
import socket
import time

import httpx
import pytest

from backend.models_radar import OpportunityStatus
from backend.services import radar_verifier, security

PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_2 = "151.101.1.69"
HOST = "jobs.rebind-example.test"
APPLY_PAGE = "<html><body><h1>Software Intern</h1><a>Apply now</a></body></html>"


def _addrinfo(ips):
    """One getaddrinfo answer; `ips` is a single address or a list of addresses (returned in order)."""
    ips = [ips] if isinstance(ips, str) else ips
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in ips
    ]


class FakeDns:
    """Serves one answer per lookup, in order (the last answer repeats), across sync and loop lookups."""

    def __init__(self, monkeypatch, answers):
        self.answers = list(answers)
        self.sync_calls = 0
        self.loop_calls = 0
        monkeypatch.setattr(security.socket, "getaddrinfo", self._sync)
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", self._loop)

    def _answer(self):
        ip = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return _addrinfo(ip)

    def _sync(self, host, *args, **kwargs):
        self.sync_calls += 1
        return self._answer()

    async def _loop(self, host, *args, **kwargs):
        self.loop_calls += 1
        return self._answer()


class FakeSend:
    """Replaces httpx.AsyncClient.send and records every request that would hit the wire."""

    def __init__(self, monkeypatch, responses):
        self.responses = list(responses)
        self.requests = []

        async def send(_client, request, **kwargs):
            return await self._send(request)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)

    async def _send(self, request):
        self.requests.append(request)
        status, text, headers = self.responses.pop(0)
        if isinstance(status, Exception):
            raise status
        return httpx.Response(status, text=text, headers=headers, request=request)


@pytest.fixture
def real_fetch(monkeypatch):
    """Use the real pinned fetch inside the verifier (the autouse fixture stubs it for hermeticity)."""
    monkeypatch.setattr(radar_verifier, "safe_http_get_with_url", security.safe_http_get_with_url)
    monkeypatch.setattr(radar_verifier, "tavily_available", lambda: False)
    # Use the real SSRF validator, not the offline-tolerant one.
    monkeypatch.setattr(radar_verifier, "is_safe_url", security.is_safe_url)


# ---------------------------------------------------------------------------
# (a) Rebinding: public on the first lookup, private on the second
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebinding_host_is_never_contacted_at_the_private_address(monkeypatch):
    dns = FakeDns(monkeypatch, [PUBLIC_IP, "10.0.0.5"])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    with pytest.raises(ValueError, match="non-global"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert send.requests == []
    assert dns.sync_calls == 1 and dns.loop_calls == 1


@pytest.mark.asyncio
async def test_connection_goes_to_the_pinned_first_resolved_ip(monkeypatch):
    # A third lookup would be internal; the pinned connection must not perform one.
    dns = FakeDns(monkeypatch, [PUBLIC_IP, PUBLIC_IP, "169.254.169.254"])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    status, text, _headers, final_url = await security.safe_http_get_with_url(f"https://{HOST}/job?x=1")

    assert status == 200 and "Apply now" in text
    assert final_url == f"https://{HOST}/job?x=1"
    assert len(send.requests) == 1
    request = send.requests[0]
    assert request.url.host == PUBLIC_IP
    assert request.url.path == "/job" and request.url.query == b"x=1"
    assert request.headers["Host"] == HOST
    assert request.extensions["sni_hostname"] == HOST.encode("ascii")
    assert dns.loop_calls == 1


@pytest.mark.asyncio
async def test_verifier_retains_status_when_the_host_rebinds(monkeypatch, real_fetch):
    FakeDns(monkeypatch, [PUBLIC_IP, "127.0.0.1"])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    status, evidence, _ = await radar_verifier.verify_opportunity_status(
        f"https://{HOST}/job", OpportunityStatus.NEEDS_VERIFICATION
    )

    assert send.requests == []
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "stopped" in evidence.lower()


# ---------------------------------------------------------------------------
# (b) Hosts resolving to internal addresses are rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("internal_ip", ["127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.5", "169.254.169.254", "::1"])
async def test_host_resolving_to_an_internal_address_is_rejected(monkeypatch, internal_ip):
    FakeDns(monkeypatch, [internal_ip])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    with pytest.raises(ValueError, match="non-global|blocked"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert send.requests == []


@pytest.mark.asyncio
async def test_verifier_never_fetches_a_host_resolving_to_metadata_address(monkeypatch, real_fetch):
    FakeDns(monkeypatch, ["169.254.169.254"])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    status, evidence, _ = await radar_verifier.verify_opportunity_status(
        f"https://{HOST}/job", OpportunityStatus.DISCOVERED
    )

    assert send.requests == []
    assert status == OpportunityStatus.DISCOVERED
    assert "not fetched" in evidence


# ---------------------------------------------------------------------------
# (c) Redirects to internal hosts are blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redirect_to_an_internal_literal_is_blocked(monkeypatch):
    FakeDns(monkeypatch, [PUBLIC_IP])
    send = FakeSend(monkeypatch, [(302, "", {"location": "http://169.254.169.254/latest/meta-data"})])

    with pytest.raises(ValueError, match="SSRF redirect blocked"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert len(send.requests) == 1


@pytest.mark.asyncio
async def test_redirect_to_a_host_that_resolves_internally_is_blocked(monkeypatch):
    dns = FakeDns(monkeypatch, [PUBLIC_IP, PUBLIC_IP, "10.0.0.9"])
    send = FakeSend(monkeypatch, [(302, "", {"location": "https://intranet.rebind-example.test/x"})])

    with pytest.raises(ValueError, match="SSRF redirect blocked"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert len(send.requests) == 1
    assert dns.sync_calls >= 2


@pytest.mark.asyncio
async def test_verifier_stops_on_a_redirect_to_an_internal_host(monkeypatch, real_fetch):
    FakeDns(monkeypatch, [PUBLIC_IP])
    send = FakeSend(monkeypatch, [(302, "", {"location": "http://10.0.0.1/admin"})])

    status, evidence, _ = await radar_verifier.verify_opportunity_status(
        f"https://{HOST}/job", OpportunityStatus.NEEDS_VERIFICATION
    )

    assert len(send.requests) == 1
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "stopped" in evidence.lower()


@pytest.mark.asyncio
async def test_too_many_redirects_retains_status(monkeypatch, real_fetch):
    FakeDns(monkeypatch, [PUBLIC_IP])
    hops = [(302, "", {"location": f"https://{HOST}/hop{i}"}) for i in range(10)]
    FakeSend(monkeypatch, hops)

    status, evidence, _ = await radar_verifier.verify_opportunity_status(
        f"https://{HOST}/job", OpportunityStatus.NEEDS_VERIFICATION
    )

    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "stopped" in evidence.lower() and "redirects" in evidence.lower()


# ---------------------------------------------------------------------------
# (d) The final URL is returned and used for judging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_final_url_after_redirect_is_returned(monkeypatch):
    FakeDns(monkeypatch, [PUBLIC_IP])
    send = FakeSend(
        monkeypatch,
        [
            (301, "", {"location": "/careers/landing"}),
            (200, APPLY_PAGE, {}),
        ],
    )

    status, _text, _headers, final_url = await security.safe_http_get_with_url(f"https://{HOST}/old")

    assert status == 200
    assert final_url == f"https://{HOST}/careers/landing"
    assert [r.url.path for r in send.requests] == ["/old", "/careers/landing"]
    assert all(r.url.host == PUBLIC_IP for r in send.requests)


@pytest.mark.asyncio
async def test_safe_http_get_keeps_its_three_tuple_contract(monkeypatch):
    FakeDns(monkeypatch, [PUBLIC_IP_2])
    FakeSend(monkeypatch, [(200, "ok", {"x-test": "1"})])

    result = await security.safe_http_get(f"https://{HOST}/")

    assert len(result) == 3
    assert result[0] == 200 and result[1] == "ok" and result[2]["x-test"] == "1"


@pytest.mark.asyncio
async def test_verifier_judges_the_landing_page_not_the_submitted_url(monkeypatch, real_fetch):
    # A specific Greenhouse posting redirects to the generic board root: an Apply button there
    # is not proof the specific vacancy is open.
    FakeDns(monkeypatch, ["52.20.0.10"])
    send = FakeSend(
        monkeypatch,
        [
            (302, "", {"location": "https://boards.greenhouse.io/acme"}),
            (200, APPLY_PAGE, {}),
        ],
    )

    status, _evidence, _ = await radar_verifier.verify_opportunity_status(
        "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.DISCOVERED
    )

    assert len(send.requests) == 2
    assert send.requests[1].headers["Host"] == "boards.greenhouse.io"
    assert status == OpportunityStatus.NEEDS_VERIFICATION


@pytest.mark.asyncio
async def test_verifier_confirms_a_specific_posting_through_the_pinned_fetch(monkeypatch, real_fetch):
    FakeDns(monkeypatch, ["52.20.0.10"])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    status, _evidence, _ = await radar_verifier.verify_opportunity_status(
        "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.DISCOVERED
    )

    assert send.requests[0].url.host == "52.20.0.10"
    assert status == OpportunityStatus.OPEN_CONFIRMED


# ---------------------------------------------------------------------------
# Multiple resolved addresses: try each pinned address in order
# ---------------------------------------------------------------------------

IPV6_PUBLIC = "2606:2800:220:1:248:1893:25c8:1946"


@pytest.mark.asyncio
async def test_unreachable_first_address_falls_back_to_the_next_pinned_address(monkeypatch):
    dns = FakeDns(monkeypatch, [[IPV6_PUBLIC, PUBLIC_IP], [IPV6_PUBLIC, PUBLIC_IP]])
    send = FakeSend(monkeypatch, [(httpx.ConnectError("refused"), "", {}), (200, APPLY_PAGE, {})])

    status, text, _headers, final_url = await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert status == 200 and "Apply now" in text
    assert [r.url.host for r in send.requests] == [IPV6_PUBLIC, PUBLIC_IP]
    assert all(r.headers["Host"] == HOST for r in send.requests)
    assert all(r.extensions["sni_hostname"] == HOST.encode("ascii") for r in send.requests)
    assert dns.loop_calls == 1
    assert final_url == f"https://{HOST}/job"


@pytest.mark.asyncio
async def test_all_addresses_failing_raises_the_last_connection_error(monkeypatch):
    FakeDns(monkeypatch, [[PUBLIC_IP, PUBLIC_IP_2]])
    send = FakeSend(
        monkeypatch,
        [(httpx.ConnectError("first refused"), "", {}), (httpx.ConnectTimeout("second timed out"), "", {})],
    )

    with pytest.raises(httpx.ConnectTimeout, match="second timed out"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert [r.url.host for r in send.requests] == [PUBLIC_IP, PUBLIC_IP_2]


@pytest.mark.asyncio
async def test_mixed_public_and_private_addresses_are_rejected_without_connecting(monkeypatch):
    FakeDns(monkeypatch, [[PUBLIC_IP, PUBLIC_IP_2], [PUBLIC_IP, "10.0.0.7"]])
    send = FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    with pytest.raises(ValueError, match="non-global"):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert send.requests == []


@pytest.mark.asyncio
async def test_non_connection_errors_do_not_trigger_fallback(monkeypatch):
    FakeDns(monkeypatch, [[PUBLIC_IP, PUBLIC_IP_2]])
    send = FakeSend(monkeypatch, [(httpx.ReadTimeout("slow"), "", {}), (200, APPLY_PAGE, {})])

    with pytest.raises(httpx.ReadTimeout):
        await security.safe_http_get_with_url(f"https://{HOST}/job")

    assert len(send.requests) == 1


# ---------------------------------------------------------------------------
# The event loop stays responsive while the blocking SSRF resolver runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_slow_ssrf_resolution(monkeypatch):
    def slow_is_safe_url(url):
        time.sleep(0.2)
        return True, ""

    monkeypatch.setattr(security, "is_safe_url", slow_is_safe_url)
    FakeDns(monkeypatch, [PUBLIC_IP])
    FakeSend(monkeypatch, [(200, APPLY_PAGE, {})])

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        await security.safe_http_get_with_url(f"https://{HOST}/job")
    finally:
        task.cancel()

    # A blocked loop would allow ~0 ticks over the 0.2s resolver call.
    assert ticks >= 5
