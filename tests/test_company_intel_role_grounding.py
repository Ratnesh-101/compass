"""Company Intel: role-specific bullets must be about the listing's role and never end mid-sentence."""

from backend.services.company_intel_jobs import build_sources_only_fallback
from backend.services.intel_grounding import (
    ROLE_MATCH,
    ROLE_NONE,
    ROLE_SIMILAR,
    role_relevance,
    shape_point_text,
)

COMPANY = "1Password"
ROLE = "Product Management Intern, End User Experience - Winter 2027"

PM_SNIPPET = (
    "You will help evolve the next generation of 1Password's product architecture, including the "
    "responsible integration of AI capabilities into core product experiences."
)
SWE_SNIPPET = (
    "As a Software Engineer at 1Password, you are responsible for building and maintaining the trust "
    "foundation that millions of individual users and organizations rely on every single day to protect "
    "their most sensitive information."
)


def _sources():
    return [
        {"id": 1, "title": "Product Management Intern - 1Password", "domain": "jobs.example.com",
         "url": "https://jobs.example.com/pm", "snippet": PM_SNIPPET},
        {"id": 2, "title": "Software Engineer - 1Password", "domain": "jobs.example.com",
         "url": "https://jobs.example.com/swe", "snippet": SWE_SNIPPET},
    ]


def test_role_relevance_rejects_software_engineer_snippet_for_pm_listing():
    assert role_relevance(SWE_SNIPPET, _sources()[1], ROLE) == ROLE_NONE


def test_role_relevance_accepts_matching_snippet():
    assert role_relevance(PM_SNIPPET, _sources()[0], ROLE) == ROLE_MATCH


def test_role_relevance_flags_other_job_family_as_similar():
    snippet = "The product engineer owns user flows for the team."
    assert role_relevance(snippet, {"snippet": snippet, "title": ""}, ROLE) == ROLE_SIMILAR


def test_shape_point_text_marks_truncation_with_ellipsis():
    out = shape_point_text(SWE_SNIPPET, 22)
    assert out["truncated"] is True
    assert out["text"].endswith("…")
    assert not out["text"].endswith("and…")


def test_shape_point_text_keeps_whole_sentence_unmarked():
    out = shape_point_text(PM_SNIPPET + " Extra trailing sentence here.", 30)
    assert out == {"text": PM_SNIPPET, "truncated": False}


def test_shape_point_text_drops_unterminated_fragment():
    assert shape_point_text("a cut off fragment that never ends and", 22) is None


def test_fallback_drops_software_engineer_bullet_for_pm_listing():
    brief = build_sources_only_fallback(_sources(), COMPANY, ROLE)
    points = [p["point"] for p in brief["role_context"]]
    assert not any("Software Engineer" in p for p in points)
    assert any(p["source"] == 1 and "product architecture" in p["point"] for p in brief["role_context"])


def test_fallback_never_emits_truncated_sentence_without_marker():
    brief = build_sources_only_fallback(_sources(), COMPANY, ROLE)
    for sec in ("priorities", "role_context", "challenges"):
        for p in brief[sec]:
            assert p["point"].endswith((".", "!", "?", "…")), p
            if p["point"].endswith("…"):
                assert p["truncated"] is True
            assert isinstance(p["source"], int)


def test_fallback_weak_role_match_is_labelled_similar_role():
    snippet = "The product engineer owns user flows for the team every quarter."
    srcs = [{"id": 1, "title": "Listing", "domain": "x.com", "url": "https://x.com", "snippet": snippet}]
    brief = build_sources_only_fallback(srcs, COMPANY, ROLE)
    assert brief["role_context"]
    assert all(p["similar_role"] is True and p["source"] == 1 for p in brief["role_context"])
