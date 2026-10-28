"""
Compass — External Submission Safety & Uncertainty Handling Verification Suite.

Validates the complete submission lifecycle across all 10 failure & edge-case scenarios:
1. ATS rejects submission (HTTP 400/500).
2. ATS accepts submission (HTTP 200/201) and records success.
3. ATS times out before outcome is known (transitions to SUBMISSION_OUTCOME_UNKNOWN; retry blocked).
4. ATS accepts request but Compass fails before persisting response (remains SUBMITTING, reconciled safely).
5. Database fails before submission (atomic claim fails, no external call made).
6. Database fails after external submission (reconciled to SUBMISSION_OUTCOME_UNKNOWN).
7. Worker crashes while holding a claim (stale claim reconciliation recycles batch, sets app to UNKNOWN).
8. Duplicate request arrives concurrently (concurrency lock/claim rejection blocks duplicate).
9. Replay of previously used confirmation token (rejected with HTTP 409 Conflict).
10. Operator/user reconciles an unknown outcome safely.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import httpx
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.memory.career import (
    approve_application_batch,
    claim_application_batch_for_submission,
    claim_career_application_for_submission,
    create_application_batch,
    finish_application_batch,
    get_application_batch,
    get_career_application_by_id,
    get_or_create_career_application,
    get_pool,
    reconcile_stale_submission_claims,
    update_career_application,
    upsert_master_resume,
)
from backend.memory.radar import upsert_opportunity
from backend.models_career import (
    CareerApplicationStatus,
    ResumeContent,
    SubmissionMethod,
)
from backend.services.career_submission import (
    AtsEndpointAdapter,
    execute_batch_submission,
    generate_batch_approval_token,
    submit_single_application,
)


@pytest.fixture(autouse=True)
async def setup_test_opportunity():
    """Ensure valid opportunities exist in PostgreSQL to satisfy foreign key constraints."""
    await upsert_opportunity(
        company_name="Safety Test Corp",
        role_title="Platform Engineer Intern",
        canonical_url="https://safety.test.corp/jobs/intern-1",
    )


# ---------------------------------------------------------------------------
# Scenario 1: ATS rejects submission
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_1_ats_rejects_submission():
    user = "s1_user"
    opp_id = await upsert_opportunity("S1 Corp", "Dev", "https://s1.corp/jobs/1")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    adapter = AtsEndpointAdapter()
    mock_resp = httpx.Response(400, text="Invalid candidate data: missing transcript")

    with patch.dict("os.environ", {"ATS_ENTERPRISE_API_KEY": "test-key"}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await adapter.execute(app_rec, {"company_name": "S1 Corp", "role_title": "Dev"}, None, user)

    assert res.status == CareerApplicationStatus.SUBMISSION_FAILED.value
    updated = await get_career_application_by_id(app_rec.id, user)
    assert updated is not None
    assert updated.status == CareerApplicationStatus.SUBMISSION_FAILED.value
    assert updated.submission_result is not None
    assert "Invalid candidate data" in updated.submission_result.get("error", "")


# ---------------------------------------------------------------------------
# Scenario 2: ATS accepts submission and Compass records success
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_2_ats_accepts_submission():
    user = "s2_user"
    opp_id = await upsert_opportunity("S2 Corp", "Dev", "https://s2.corp/jobs/2")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    adapter = AtsEndpointAdapter()
    mock_resp = httpx.Response(200, json={"reference_id": "ATS-REF-9999", "status": "received"})

    with patch.dict("os.environ", {"ATS_ENTERPRISE_API_KEY": "test-key"}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await adapter.execute(app_rec, {"company_name": "S2 Corp", "role_title": "Dev"}, None, user)

    assert res.status == CareerApplicationStatus.SUBMISSION_SUBMITTED.value if hasattr(CareerApplicationStatus, 'SUBMISSION_SUBMITTED') else res.status == CareerApplicationStatus.SUBMITTED.value
    updated = await get_career_application_by_id(app_rec.id, user)
    assert updated is not None
    assert updated.status == CareerApplicationStatus.SUBMITTED.value
    assert updated.submission_result is not None
    assert updated.submission_result.get("reference_id") == "ATS-REF-9999"
    assert updated.submitted_at is not None


# ---------------------------------------------------------------------------
# Scenario 3: ATS times out before outcome is known (SUBMISSION_OUTCOME_UNKNOWN)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_3_ats_times_out_unknown_outcome():
    user = "s3_user"
    opp_id = await upsert_opportunity("S3 Corp", "Dev", "https://s3.corp/jobs/3")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    adapter = AtsEndpointAdapter()
    with patch.dict("os.environ", {"ATS_ENTERPRISE_API_KEY": "test-key"}), \
         patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Connection timed out")):
        res = await adapter.execute(app_rec, {"company_name": "S3 Corp", "role_title": "Dev"}, None, user)

    assert res.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value
    updated = await get_career_application_by_id(app_rec.id, user)
    assert updated is not None
    assert updated.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value

    # Verify automated retry is BLOCKED
    retry_res = await submit_single_application(app_rec.id, user, SubmissionMethod.ATS_ENDPOINT)
    assert retry_res.status == "BLOCKED"
    assert "uncertain outcome" in retry_res.message


# ---------------------------------------------------------------------------
# Scenario 4: ATS accepts request but Compass fails before persisting response
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_4_ats_accepted_but_local_save_crashes():
    user = "s4_user"
    opp_id = await upsert_opportunity("S4 Corp", "Dev", "https://s4.corp/jobs/4")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    # Leave application in SUBMITTING status (simulating a crash between external call and final update)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.SUBMITTING.value,
    })

    # Age record by 15 minutes
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE career_applications SET updated_at = $1 WHERE id = $2", stale_time, app_rec.id)

    # Stale claim reconciler must safely transition to SUBMISSION_OUTCOME_UNKNOWN
    reconciled = await reconcile_stale_submission_claims(user, max_age_seconds=600)
    assert reconciled["reconciled_applications"] >= 1

    recovered = await get_career_application_by_id(app_rec.id, user)
    assert recovered is not None
    assert recovered.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value


# ---------------------------------------------------------------------------
# Scenario 5: Database fails before submission (atomic claim fails)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_5_db_fails_before_submission():
    user = "s5_user"
    opp_id = await upsert_opportunity("S5 Corp", "Dev", "https://s5.corp/jobs/5")
    app_rec = await get_or_create_career_application(user, opp_id)

    # If atomic claim fails because DB is down or claim is rejected, external submission is NEVER called
    with patch("backend.memory.career.claim_career_application_for_submission", return_value=False), \
         patch("httpx.AsyncClient.post") as mock_post:
        res = await submit_single_application(app_rec.id, user, SubmissionMethod.ATS_ENDPOINT)
        assert res.status == "BLOCKED"
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 6: Database fails after external submission
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_6_db_fails_after_external_submission():
    user = "s6_user"
    opp_id = await upsert_opportunity("S6 Corp", "Dev", "https://s6.corp/jobs/6")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.SUBMITTING.value,
    })

    # Record left in SUBMITTING because DB update failed; verified that reconciler catches it
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE career_applications SET updated_at = $1 WHERE id = $2", stale_time, app_rec.id)

    res = await reconcile_stale_submission_claims(user, max_age_seconds=600)
    assert res["reconciled_applications"] >= 1
    recovered = await get_career_application_by_id(app_rec.id, user)
    assert recovered is not None
    assert recovered.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value


# ---------------------------------------------------------------------------
# Scenario 7: Worker crashes while holding claim
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_7_worker_crashes_holding_claim():
    # Unique user per run: a stale SUBMISSION_OUTCOME_UNKNOWN row from a prior run must not be re-approved.
    user = f"s7_user_{uuid.uuid4().hex[:8]}"
    opp_id = await upsert_opportunity("S7 Corp", "Dev", "https://s7.corp/jobs/7")
    app_rec = await get_or_create_career_application(user, opp_id)
    batch_id = await create_application_batch(user, [app_rec.id])
    await approve_application_batch(batch_id, user, "bat_token_s7")
    await claim_application_batch_for_submission(batch_id, user)
    await claim_career_application_for_submission(app_rec.id, user)

    # Worker dies; time passes
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE career_applications SET updated_at = $1 WHERE id = $2", stale_time, app_rec.id)
            await conn.execute("UPDATE application_batches SET updated_at = $1 WHERE id = $2", stale_time, batch_id)

    rec = await reconcile_stale_submission_claims(user, max_age_seconds=600)
    assert rec["reconciled_applications"] >= 1
    assert rec["reconciled_batches"] >= 1

    recovered_batch = await get_application_batch(batch_id, user)
    assert recovered_batch is not None
    assert recovered_batch["status"] == "READY_FOR_REVIEW"
    assert recovered_batch["approval_token"] is None


# ---------------------------------------------------------------------------
# Scenario 8: Duplicate request arrives concurrently
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_8_concurrent_duplicate_request():
    user = "s8_user"
    opp_id = await upsert_opportunity("S8 Corp", "Dev", "https://s8.corp/jobs/8")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    # First claim succeeds
    claim1 = await claim_career_application_for_submission(app_rec.id, user)
    assert claim1 is True

    # Second concurrent claim must fail
    claim2 = await claim_career_application_for_submission(app_rec.id, user)
    assert claim2 is False


# ---------------------------------------------------------------------------
# Scenario 9: Replay of previously used confirmation token
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_9_replay_of_used_approval_token():
    user = "s9_user"
    opp_id = await upsert_opportunity("S9 Corp", "Dev", "https://s9.corp/jobs/9")
    app_rec = await get_or_create_career_application(user, opp_id)
    batch_id = await create_application_batch(user, [app_rec.id])
    await approve_application_batch(batch_id, user, "bat_token_s9_replay")
    await finish_application_batch(batch_id, user, [{"application_id": app_rec.id, "status": "SUBMITTED"}])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id, "approval_token": "bat_token_s9_replay"},
            headers={"x-user-id": user},
        )
        assert res.status_code == 409
        assert "Duplicate submission rejected" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Scenario 10: Unknown outcome is reconciled safely
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_10_unknown_outcome_reconciled():
    user = "s10_user"
    opp_id = await upsert_opportunity("S10 Corp", "Dev", "https://s10.corp/jobs/10")
    app_rec = await get_or_create_career_application(user, opp_id)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value,
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Operator or candidate verifies with employer and reconciles status to SUBMITTED
        res = await client.patch(
            f"/api/career/applications/{app_rec.id}",
            json={
                "status": "SUBMITTED",
                "private_notes": "Verified received via confirmation email from HR team",
            },
            headers={"x-user-id": user},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUBMITTED"
        assert "Verified received" in data["private_notes"]
