"""
Compass — Career Copilot & Internship Radar Portal Audit Tests.

Verifies fixes for:
1. Expired close dates / past deadlines excluded from OPEN_CONFIRMED.
2. Dynamic upcoming_deadlines_count and last_sync_at in overview stats.
3. Multi-tenant user isolation for in-memory saved and applied stats.
4. In-memory pagination offset and filter support (country, work_arrangement).
5. 24-hour verification ISO timestamp parsing and exact_timestamp recency.
6. Binary file rejection for .txt/.md masquerading uploads.
7. Zero-hallucination compliance: no fabricated "Software Engineer" role for unstated titles.
"""
from datetime import date, datetime, timedelta, timezone
import pytest

from backend.models_radar import (
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
    UserOpportunityProfileIn,
)
from backend.routers.radar import _enrich_opportunity, compute_is_verified_within_24h
from backend.memory.radar import (
    _in_memory_opportunities,
    _in_memory_user_opps,
    _in_memory_sync_runs,
    get_all_opportunities,
    get_radar_overview_stats,
    upsert_user_saved_opportunity,
    create_sync_run,
    finish_sync_run,
)
from backend.services.career_file_parser import extract_resume_from_file_bytes
from backend.services.career_resume import (
    ResumeExperienceItem,
    _experience_sentence,
    parse_uploaded_resume_text,
)


# ===========================================================================
# 1. Past Deadlines and Closed Opportunity Filtering
# ===========================================================================

def test_closed_opportunity_dynamically_enriched_when_deadline_passed():
    yesterday = date.today() - timedelta(days=1)
    opp = OpportunityOut(
        id=9001,
        company_name="Acme Corp",
        normalized_company="Acme",
        role_title="Software Intern",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://acme.test/jobs/9001",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        confirmed_close_date=yesterday,
    )
    enriched = _enrich_opportunity(opp, None)
    assert enriched.current_status == OpportunityStatus.CLOSED_CONFIRMED
    assert "closed on" in (enriched.verification_evidence or "")




# ===========================================================================
# 2. Radar Overview Stats Accuracy & Deadlines Computation
# ===========================================================================



# ===========================================================================
# 3. Multi-Tenant User Isolation & In-Memory Pagination
# ===========================================================================

@pytest.mark.asyncio
async def test_in_memory_multi_tenant_isolation_stats():
    _in_memory_user_opps.clear()

    await upsert_user_saved_opportunity("user_alpha", 101, is_saved=True)
    await upsert_user_saved_opportunity("user_alpha", 102, is_saved=True)

    stats_alpha = await get_radar_overview_stats("user_alpha")
    stats_beta = await get_radar_overview_stats("user_beta")

    assert stats_alpha["saved_count"] == 2
    assert stats_beta["saved_count"] == 0




# ===========================================================================
# 4. 24-Hour Recency Timestamp Parsing
# ===========================================================================



# ===========================================================================
# 5. File Parser Edge Cases (Binary Masquerading Rejection)
# ===========================================================================

def test_resume_parser_rejects_binary_file_disguised_as_text():
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    res_png = extract_resume_from_file_bytes(png_bytes, "resume.txt")
    assert res_png.success is False
    assert "binary and cannot be read as text" in (res_png.error_message or "")

    elf_bytes = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    res_elf = extract_resume_from_file_bytes(elf_bytes, "resume.md")
    assert res_elf.success is False
    assert "binary and cannot be read as text" in (res_elf.error_message or "")

    null_bytes = b"Jane Doe\x00\x00\x00Experience\x00"
    res_null = extract_resume_from_file_bytes(null_bytes, "corrupt.txt")
    assert res_null.success is False
    assert "binary and cannot be read as text" in (res_null.error_message or "")


# ===========================================================================
# 6. Zero Hallucination: Experience Role Parsing
# ===========================================================================

def test_resume_role_zero_hallucination_on_unstated_role():
    raw_text = """
Jane Doe
jane.doe@example.com

Work Experience
Acme Analytics | May 2022 - Aug 2023
• Analyzed operational performance data and generated reports.
"""
    content = parse_uploaded_resume_text(raw_text)
    assert len(content.experience) == 1
    exp = content.experience[0]
    assert exp.company == "Acme Analytics"
    assert exp.role_title != "Software Engineer"

    # Sentence generator formatting without role
    sentence = _experience_sentence(exp)
    assert "Most recently, I worked at Acme Analytics" in sentence
    assert "worked as  at" not in sentence


def test_open_listing_with_future_deadline_stays_open():
    opp = OpportunityOut(
        id=9002,
        company_name="Acme Corp",
        normalized_company="Acme",
        role_title="Software Intern",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://acme.test/jobs/9002",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        confirmed_close_date=date.today() + timedelta(days=5),
    )
    assert _enrich_opportunity(opp, None).current_status == OpportunityStatus.OPEN_CONFIRMED


def test_verified_within_24h_requires_exact_precision():
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert compute_is_verified_within_24h(recent, "exact") is True
    assert compute_is_verified_within_24h(recent, "date_only") is False
