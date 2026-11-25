"""TLS certificate failures are not 'fetch failures', and the re-check cadence is daily (no network, no DB)."""
from datetime import datetime, timezone

import pytest

from backend.models_radar import OpportunityStatus
from backend.services import radar_reverify, radar_verifier
from backend.services.radar_verifier import (
    is_fetch_failure,
    is_tls_certificate_error,
    verify_opportunity_status,
)

JOB = "https://boards.greenhouse.io/acme/jobs/1234567"
TLS_TEXT = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch"


@pytest.mark.parametrize(
    "text",
    [
        TLS_TEXT,
        "ssl.SSLCertVerificationError: certificate has expired",
        "self-signed certificate in certificate chain",
        "certificate verify failed",
    ],
)
def test_tls_errors_detected(text):
    assert is_tls_certificate_error(text) is True


@pytest.mark.parametrize(
    "text",
    ["Connection timed out", "Name or service not known", "HTTP 503", "", None],
)
def test_non_tls_errors_not_detected(text):
    assert is_tls_certificate_error(text) is False


def _patch_raising_fetch(monkeypatch, exc):
    async def fake(url, **kwargs):
        raise exc

    monkeypatch.setattr(radar_verifier, "safe_http_get_with_url", fake)
    monkeypatch.setattr(radar_verifier, "is_safe_url", lambda url: (True, ""))
    monkeypatch.setattr(radar_verifier, "tavily_available", lambda: False)


@pytest.mark.asyncio
async def test_tls_failure_needs_verification_and_is_not_fetch_failure(monkeypatch):
    _patch_raising_fetch(monkeypatch, Exception(TLS_TEXT))
    status, evidence, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert status not in (OpportunityStatus.OPEN_CONFIRMED, OpportunityStatus.CLOSED_CONFIRMED)
    assert "security certificate" in evidence
    assert is_fetch_failure(evidence) is False


@pytest.mark.asyncio
async def test_generic_timeout_is_still_fetch_failure(monkeypatch):
    _patch_raising_fetch(monkeypatch, Exception("Connection timed out"))
    status, evidence, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.OPEN_CONFIRMED
    assert is_fetch_failure(evidence) is True


def test_recheck_constants():
    assert radar_reverify.RECHECK_AFTER_DAYS == 1
    assert radar_reverify.DEFAULT_BATCH_SIZE == 100


@pytest.mark.asyncio
async def test_reverify_persists_tls_demotion(monkeypatch):
    row = {
        "id": 7,
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "last_verified_at": None,
        "application_url": JOB,
    }

    async def fake_select(limit=100):
        return [row]

    saved = []

    async def fake_update(**kwargs):
        saved.append(kwargs)

    async def fake_verify(url, current_status):
        return OpportunityStatus.NEEDS_VERIFICATION, "invalid security certificate", datetime.now(timezone.utc)

    monkeypatch.setattr(radar_reverify, "select_stale_open_opportunities", fake_select)
    monkeypatch.setattr(radar_reverify.radar_memory, "update_opportunity_verification", fake_update)

    res = await radar_reverify.reverify_stale_opportunities(limit=5, verify=fake_verify)

    assert res["checked"] == 1
    assert res["downgraded"] == 1
    assert res["still_open"] == 0
    assert res["errors"] == 0
    assert len(saved) == 1
    assert saved[0]["opportunity_id"] == 7
    assert saved[0]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
    assert saved[0]["verification_evidence"] == "invalid security certificate"
