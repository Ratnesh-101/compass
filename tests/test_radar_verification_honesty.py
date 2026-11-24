"""Verification honesty: redirects to error/general pages must not read as open (no network, no DB)."""
import re
from pathlib import Path

import pytest

from backend.models_radar import OpportunityStatus
from backend.services import radar_verifier
from backend.services.radar_verifier import redirect_signals_closed, verify_opportunity_status

JOB = "https://boards.greenhouse.io/acme/jobs/1234567"
SYNC_PATH = Path(__file__).resolve().parent.parent / "backend" / "services" / "radar_sync.py"


@pytest.mark.parametrize(
    "final",
    [
        JOB + "?error=true",
        "https://boards.greenhouse.io/acme/error",
        "https://boards.greenhouse.io/acme/not-found",
        "https://boards.greenhouse.io/404",
        "https://example.com/job-not-found",
    ],
)
def test_redirect_to_error_page_is_closed(final):
    result = redirect_signals_closed(JOB, final)
    assert result is not None
    status, evidence = result
    assert status == OpportunityStatus.CLOSED_CONFIRMED
    assert evidence


@pytest.mark.parametrize(
    "final",
    [
        "https://acme.com/",
        "https://acme.com/careers",
        "https://acme.com/jobs",
        "https://acme.com/openings",
        "https://boards.greenhouse.io/acme",
        "https://boards.greenhouse.io/",
    ],
)
def test_redirect_to_general_page_needs_verification(final):
    result = redirect_signals_closed(JOB, final)
    assert result is not None
    status, evidence = result
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert evidence


@pytest.mark.parametrize(
    "final",
    [
        JOB,
        JOB + "?gh_src=abc",
        JOB.replace("https://", "http://"),
        JOB + "/",
        "https://www.boards.greenhouse.io/acme/jobs/1234567",
    ],
)
def test_benign_redirects_are_not_signals(final):
    assert redirect_signals_closed(JOB, final) is None


def test_http_to_https_and_www_are_not_signals():
    assert redirect_signals_closed("http://acme.com/careers/role-1", "https://acme.com/careers/role-1") is None
    assert redirect_signals_closed("https://acme.com/careers/role-1", "https://www.acme.com/careers/role-1") is None
    assert redirect_signals_closed("https://www.acme.com/careers/role-1", "https://acme.com/careers/role-1") is None


def _patch_fetch(monkeypatch, status, final_url, text=""):
    async def fake(url, **kwargs):
        return status, text, {}, final_url

    monkeypatch.setattr(radar_verifier, "safe_http_get_with_url", fake)
    monkeypatch.setattr(radar_verifier, "is_safe_url", lambda url: (True, ""))
    monkeypatch.setattr(radar_verifier, "tavily_available", lambda: False)


@pytest.mark.asyncio
async def test_error_redirect_closes(monkeypatch):
    _patch_fetch(monkeypatch, 200, JOB + "?error=true", "Apply now")
    status, evidence, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.CLOSED_CONFIRMED
    assert evidence


@pytest.mark.asyncio
async def test_redirect_to_homepage_never_open(monkeypatch):
    _patch_fetch(monkeypatch, 200, "https://acme.com/", "Apply now")
    status, _, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert status != OpportunityStatus.OPEN_CONFIRMED


@pytest.mark.asyncio
async def test_http_404_still_closed(monkeypatch):
    _patch_fetch(monkeypatch, 404, JOB)
    status, _, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.CLOSED_CONFIRMED


@pytest.mark.asyncio
async def test_unchanged_ats_requisition_keeps_result(monkeypatch):
    _patch_fetch(monkeypatch, 200, JOB)
    status, _, _ = await verify_opportunity_status(JOB, OpportunityStatus.OPEN_CONFIRMED)
    assert status == OpportunityStatus.OPEN_CONFIRMED


def test_curated_ingest_does_not_fake_verification():
    src = SYNC_PATH.read_text(encoding="utf-8")
    start = src.index("# 1. Ingest Curated")
    nxt = re.compile(r"#\s*2\.").search(src, start)
    assert nxt is not None, "next numbered step comment not found"
    block = src[start:nxt.start()]
    assert "last_verified_at=datetime.now(timezone.utc)" not in block
    assert "application_url_checked=False" in block
