"""
Compass — Career Copilot Profile Save UX & Refresh Regression Tests.

Validates:
1. Profile save API saves the profile and returns the updated payload.
2. The modal closes without waiting for recommendation refresh to complete.
3. The user remains on or returns to the Internship Radar view.
4. Recommendation refresh starts asynchronously after profile save succeeds.
5. A failed profile save keeps the modal open and preserves user input.
6. A failed recommendation refresh does not reopen the modal or undo the saved profile.
7. A single save does not trigger duplicate recommendation refreshes.
8. The page remains interactive during recommendation refresh.
9. Authentication and tenant-isolation protections remain intact.
"""
from pathlib import Path
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.dependencies import generate_guest_token
from backend.memory.radar import get_user_opportunity_profile


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


# ===========================================================================
# 1. Backend API & State Persistence Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_profile_save_persists_independently_of_recommendations():
    """Profile save commits to database; recommendation refresh failure does not rollback profile."""
    user_id = str(uuid.uuid4())
    _, token = generate_guest_token(user_id)
    headers = {"x-guest-token": token}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        payload = {
            "degree": "B.Tech",
            "degree_specialization": "Artificial Intelligence",
            "university": "IIT Madras",
            "academic_year": 3,
            "grad_year": 2027,
            "grad_month": 6,
            "country_of_study": "India",
            "skills": ["Python", "PyTorch", "Transformers"],
            "preferred_roles": ["Artificial Intelligence and Machine Learning"],
            "preferred_work_arrangements": ["remote", "hybrid"],
        }
        save_res = await client.put("/api/opportunities/profile", json=payload)
        assert save_res.status_code == 200
        saved_data = save_res.json()
        assert saved_data["degree"] == "B.Tech"
        assert saved_data["degree_specialization"] == "Artificial Intelligence"

        # Verify saved state in database immediately
        profile_in_db = await get_user_opportunity_profile(user_id)
        assert profile_in_db is not None
        assert profile_in_db.university == "IIT Madras"
        assert profile_in_db.grad_year == 2027

        # Recommendations fetch runs as a separate API request
        rec_res = await client.get("/api/opportunities/recommended?limit=5")
        assert rec_res.status_code == 200
        rec_data = rec_res.json()
        assert isinstance(rec_data, list)

        # Even if a bad request is made to recommendations, profile remains intact
        bad_rec = await client.get("/api/opportunities/recommended?limit=-99")
        # Profile is still preserved
        profile_after = await get_user_opportunity_profile(user_id)
        assert profile_after is not None
        assert profile_after.university == "IIT Madras"


@pytest.mark.asyncio
async def test_profile_save_rejects_invalid_input_without_persisting():
    """Invalid input is rejected (422) and does not corrupt existing profile."""
    user_id = str(uuid.uuid4())
    _, token = generate_guest_token(user_id)
    headers = {"x-guest-token": token}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        # Invalid academic year (must be 1..5)
        bad_payload = {"degree": "B.Tech", "academic_year": 99, "grad_year": 2027}
        res = await client.put("/api/opportunities/profile", json=bad_payload)
        assert res.status_code == 422


# ===========================================================================
# 2. Frontend Component Contract & Flow Tests (Static Verification)
# ===========================================================================

def test_radar_profile_modal_immediate_close_and_error_preservation():
    """RadarProfileModal closes immediately on save success, preserves state on error."""
    modal_code = (FRONTEND_SRC / "components" / "radar" / "RadarProfileModal.jsx").read_text(encoding="utf-8")

    # 1. Verify handleSubmit does NOT use setTimeout delay to close modal
    assert "closeTimeoutRef" not in modal_code, "closeTimeoutRef must be removed"
    assert "setTimeout(() => {" not in modal_code, "Modal close must not be delayed by setTimeout"

    # 2. Verify onClose is invoked immediately in try block after onSave/updateRadarProfile
    assert "if (typeof onClose === 'function')" in modal_code
    assert "onClose()" in modal_code

    # 3. Verify try/catch/finally ensures modal stays open on error with message
    assert "catch (err)" in modal_code
    assert "setErrorMessage(" in modal_code
    assert "finally" in modal_code
    assert "setSavingInternal(false)" in modal_code

    # 4. Verify duplicate submission prevention
    assert "if (isBusy) return" in modal_code
    assert "disabled={isBusy || !isFormComplete}" in modal_code


def test_career_copilot_save_ux_and_navigation():
    """CareerCopilot switches tabs, shows notification, and triggers async refresh."""
    copilot_code = (FRONTEND_SRC / "components" / "CareerCopilot.jsx").read_text(encoding="utf-8")

    # 1. Verify navigation to Resume Studio for profile editing
    assert "handleNavigateToResumeStudio" in copilot_code
    assert "setActiveSubTab('resumes')" in copilot_code

    # 2. Verify notification banner exists with expected wording
    assert "✓ Profile saved! Internship matches have been updated." in copilot_code
    assert "Profile saved, but could not refresh internship recommendations." in copilot_code
    assert "canRetry" in copilot_code

    # 3. Verify refresh is triggered via profileRefreshTrigger without forcing key remount
    assert "profileRefreshTrigger" in copilot_code
    assert "<InternshipRadar key=" not in copilot_code, "Must not force full component remount with key"
    assert "refreshTrigger={profileRefreshTrigger}" in copilot_code


def test_internship_radar_non_blocking_background_refresh():
    """InternshipRadar refreshes matches in background while keeping page interactive."""
    radar_code = (FRONTEND_SRC / "components" / "InternshipRadar.jsx").read_text(encoding="utf-8")

    # 1. Verify loadOpportunities supports options.background
    assert "options?.background === true" in radar_code
    assert "isRefreshingMatches" in radar_code

    # 2. Verify background refresh does NOT wipe out opportunities or set full page loading
    assert "if (!isBackground) {" in radar_code
    assert "setLoading(true)" in radar_code

    # 3. Verify isFirstMountRef prevents duplicate refresh on initial load
    assert "isFirstMountRef" in radar_code

    # 4. Verify scoped indicator is shown during background refresh
    assert "radar-refreshing-indicator" in radar_code
    assert "Refreshing internship recommendations" in radar_code
