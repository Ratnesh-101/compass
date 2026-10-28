"""
Compass — Tavily Claim Resolution, Evidence Accuracy & Structured Contract Tests.

Validates:
1. Button-based verification targets exact assistant message.
2. Conversational intents ("Verify this with Tavily", "Verify it with Tavily", "Can you verify that?",
   "Check this deadline with Tavily", "Fact-check the previous answer", "Verify the claim you just made")
   resolve the preceding assistant answer.
3. The verification instruction is never interpreted as the claim.
4. Cross-tenant and cross-conversation message IDs are rejected.
5. Clean quotation truncation without mid-word cutoffs.
6. Contradictory dates produce CONTRADICTED verdicts.
7. Structured evidence contract contains clean, unescaped links and no duplicate presentation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from backend.router_helpers import (
    is_tavily_verification_intent,
    extract_claim_and_entity_from_text,
    resolve_verification_claim_and_entity,
)
from backend.services.tavily_pipeline import (
    truncate_quote_cleanly,
    sanitize_verification_query,
    evaluate_deterministic_verdict,
    decompose_query,
)
from backend.skills.handlers.web import handle_verify_with_tavily
from backend.models import MessageOut, MessagesResponse


# ============================================================================
# PHASE 7: CLAIM RESOLUTION TESTS
# ============================================================================

def test_button_target_message_content_used_directly():
    """1. Direct target message content is resolved as the claim subject."""
    assistant_text = "The Nebius x NVIDIA Global AI Hackathon's submission deadline is October 30, 2026, at 1:00 PM EDT."
    claim, entity = extract_claim_and_entity_from_text(assistant_text)
    assert "Nebius" in claim
    assert "October 30, 2026" in claim
    assert entity and "Nebius" in entity


def test_conversational_intents_recognized():
    """2 & 3. Conversational follow-ups are recognized as verification intents."""
    intents = [
        "Verify this with Tavily.",
        "Verify it with Tavily.",
        "Can you verify that?",
        "Check this deadline with Tavily.",
        "Fact-check the previous answer.",
        "Verify the claim you just made.",
        "Verify the Nebius deadline with Tavily.",
        "Please verify that with Tavily",
        "Can you check this claim with tavily?",
    ]
    for prompt in intents:
        assert is_tavily_verification_intent(prompt), f"Failed to detect intent: {prompt}"


def test_verification_instruction_never_interpreted_as_claim():
    """5. The verification instruction string itself is never accepted as a factual claim."""
    claim, entity = extract_claim_and_entity_from_text("Verify this with Tavily")
    assert claim == ""
    assert entity is None

    claim2, entity2 = extract_claim_and_entity_from_text("Can you verify that?")
    assert claim2 == ""
    assert entity2 is None


@pytest.mark.asyncio
async def test_resolve_from_recent_history():
    """2 & 4. Resolves from preceding assistant message, skipping unrelated old messages."""
    history = [
        {"role": "user", "content": "Tell me about quantum computing"},
        {"role": "assistant", "content": "Quantum computers use qubits."},
        {"role": "user", "content": "When is the Nebius hackathon due?"},
        {
            "role": "assistant",
            "content": "The Nebius x NVIDIA Global AI Hackathon deadline is October 30, 2026 at 1:00 PM EDT.",
        },
    ]
    claim, entity = await resolve_verification_claim_and_entity(
        message="Verify this with Tavily",
        recent_history=history,
    )
    assert "Nebius" in claim
    assert "October 30, 2026" in claim
    assert entity and "Nebius" in entity


@pytest.mark.asyncio
async def test_cross_tenant_message_id_rejected():
    """6. Rejects foreign tenant / user message ID lookup."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # Not found for this user
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    claim, entity = await resolve_verification_claim_and_entity(
        message="Verify this with Tavily",
        target_message_id="00000000-0000-0000-0000-000000000001",
        user_id="user_alice",
        pool=mock_pool,
        recent_history=[],
    )
    assert claim == ""
    assert entity is None


# ============================================================================
# PHASE 7: EVIDENCE ACCURACY & CONTRADICTION TESTS
# ============================================================================

def test_clean_quote_truncation_preserves_sentence_boundary():
    """18. truncate_quote_cleanly avoids cutting off midway through a word or sentence."""
    long_text = (
        "Submissions close on October 30, 2026 at 1:00 PM EDT. "
        "All participants must submit their project repositories along with a demonstration video before this time. "
        "Late submissions will not be evaluated under any circumstances by the judging panel."
    )
    truncated = truncate_quote_cleanly(long_text, max_chars=120)
    # Must end at sentence boundary or clean ellipsis, not in the middle of a word like "submi"
    assert not truncated.endswith("submi")
    assert truncated.endswith(".") or truncated.endswith("...")
    assert "Submissions close on October 30, 2026 at 1:00 PM EDT." in truncated


def test_sanitize_verification_query_strips_intent_words():
    """9. Research queries do not search for Tavily terms when verifying an event claim."""
    q1 = sanitize_verification_query("Verify this with Tavily")
    assert "tavily" not in q1.lower()

    q2 = sanitize_verification_query("Verify the Nebius deadline with Tavily")
    assert "tavily" not in q2.lower()
    assert "Nebius deadline" in q2


@pytest.mark.asyncio
async def test_decompose_query_focuses_on_topic():
    """8. Query decomposition produces topic-specific subqueries without Tavily pollution."""
    subqueries = await decompose_query("The Nebius x NVIDIA Global AI Hackathon deadline")
    for sq in subqueries:
        assert "tavily" not in sq.lower()
        assert "nebius" in sq.lower()


def test_incorrect_prior_claim_date_produces_contradicted_verdict():
    """11 & Test D. An intentionally wrong claim date is contradicted by authoritative evidence."""
    # Prior claim had wrong date: October 15, 2026
    wrong_claim = "The submission deadline for the Nebius x NVIDIA Global AI Hackathon is October 15, 2026"

    # Official Devpost evidence has: October 30, 2026
    claims = [
        {
            "claim": "Submissions close October 30, 2026 at 1:00 PM EDT",
            "source_url": "https://nebius-nvidia.devpost.com/rules",
            "exact_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.",
            "extracted_date": "October 30, 2026",
        }
    ]
    sources = [
        {
            "url": "https://nebius-nvidia.devpost.com/rules",
            "authority_tier": "tier_1_official",
            "authority_badge": "Official Organizer",
            "content": "Submissions close October 30, 2026 at 1:00 PM EDT.",
        }
    ]
    raw_text = "Submissions close October 30, 2026 at 1:00 PM EDT."

    verdict, evidence_items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=raw_text,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius-nvidia.devpost.com/rules": raw_text},
        target_claim=wrong_claim,
    )

    assert verdict == "CONTRADICTED"
    assert evidence_items[0]["verdict"] == "CONTRADICTED"


def test_correct_prior_claim_date_produces_verified_verdict():
    """8. A correct claim date matching authoritative evidence is VERIFIED."""
    correct_claim = "The submission deadline for the Nebius x NVIDIA Global AI Hackathon is October 30, 2026"
    claims = [
        {
            "claim": "Submissions close October 30, 2026 at 1:00 PM EDT",
            "source_url": "https://nebius-nvidia.devpost.com/rules",
            "exact_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.",
            "extracted_date": "October 30, 2026",
        }
    ]
    sources = [
        {
            "url": "https://nebius-nvidia.devpost.com/rules",
            "authority_tier": "tier_1_official",
            "authority_badge": "Official Organizer",
            "content": "Submissions close October 30, 2026 at 1:00 PM EDT.",
        }
    ]
    raw_text = "Submissions close October 30, 2026 at 1:00 PM EDT."

    verdict, evidence_items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=raw_text,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius-nvidia.devpost.com/rules": raw_text},
        target_claim=correct_claim,
    )

    assert verdict == "VERIFIED"
    assert evidence_items[0]["verdict"] == "VERIFIED"


# ============================================================================
# PHASE 7: PRESENTATION & CONTRACT TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_tavily_handler_structured_contract_no_duplicates():
    """14, 15, 17. Handler returns concise narrative response and structured evidence without nested links."""
    mock_pipeline_res = {
        "verdict": "VERIFIED",
        "summary": "Authoritative Devpost rules confirm submissions close October 30, 2026 at 1:00 PM EDT.",
        "evidence_ledger": [
            {
                "verdict": "VERIFIED",
                "authority_tier": "tier_1_official",
                "authority_badge": "Official Organizer",
                "source_url": "https://nebius-nvidia.devpost.com/rules",
                "display_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.",
                "local_deadline_ist": "October 30, 2026, 22:30 IST",
            }
        ],
        "sources": [
            {
                "title": "Nebius x NVIDIA Hackathon Rules",
                "url": "https://nebius-nvidia.devpost.com/rules",
                "authority_tier": "tier_1_official",
            }
        ],
    }

    with patch("backend.services.tavily_pipeline.run_tavily_research", new=AsyncMock(return_value=mock_pipeline_res)):
        res = await handle_verify_with_tavily(
            {
                "claim": "The Nebius submission deadline is October 30, 2026",
                "target_entity": "Nebius",
                "target_message_id": "msg-123",
            },
            pool=None,
        )

    assert res["success"] is True
    # Narrative does not duplicate the list of quotes or sources
    assert "**Key Authoritative Evidence:**" not in res["response"]
    assert "**Sources Referenced:**" not in res["response"]

    # Structured contract matches Phase 6 schema
    ev = res["data"]["evidence"]
    assert ev["target_message_id"] == "msg-123"
    assert ev["verdict"] == "VERIFIED"
    assert len(ev["sources"]) == 1
    assert ev["sources"][0]["url"] == "https://nebius-nvidia.devpost.com/rules"
    assert len(ev["items"]) == 1


def test_evidence_persistence_roundtrip():
    """19 & 20. Structured evidence survives serialization into MessageOut."""
    evidence_payload = {
        "target_message_id": "msg-101",
        "claim_checked": "Nebius deadline is October 30, 2026",
        "verdict": "VERIFIED",
        "finding": "Confirmed on Devpost.",
        "sources": [{"title": "Devpost Rules", "url": "https://devpost.com/rules"}],
    }

    msg_out = MessageOut(
        id=202,
        role="assistant",
        content="### 🔍 Tavily Verification: ✅ VERIFIED",
        skill_called="verify_with_tavily",
        evidence=evidence_payload,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    resp = MessagesResponse(conversation_id="conv-1", messages=[msg_out])
    dumped = resp.model_dump()
    assert dumped["messages"][0]["evidence"]["target_message_id"] == "msg-101"
    assert dumped["messages"][0]["evidence"]["verdict"] == "VERIFIED"


@pytest.mark.asyncio
async def test_chat_stream_button_verification_e2e():
    """Phase 7 (1, 8, 14, 21): Full streaming test for button verification with server-authoritative target_message_id."""
    import json
    from backend.services.chat_stream import generate_chat_events
    from backend.models import StreamChatRequest

    req = StreamChatRequest(
        message="Verify this with Tavily",
        conversation_id="22222222-2222-2222-2222-222222222222",
        target_message_id="101",
        target_message_content="FORGED CONTENT: this client text should be ignored in favor of DB content",
    )
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    def fetchrow_side_effect(query, *args):
        q = str(query).lower()
        if "from messages" in q or "m.content" in q:
            return {
                "id": 101,
                "content": "The Nebius x NVIDIA Global AI Hackathon submission deadline is October 30, 2026 at 1:00 PM EDT.",
                "role": "assistant",
            }
        return {
            "id": "22222222-2222-2222-2222-222222222222",
            "title": "Hackathon Chat",
            "user_id": "user_alice",
            "guest_id": None,
            "exists": True,
        }
    mock_conn.fetchrow.side_effect = fetchrow_side_effect
    mock_conn.fetchval.return_value = True
    mock_conn.execute.return_value = "OK"
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    events = []
    with patch("backend.services.chat_stream._resolve_pool", new=AsyncMock(return_value=mock_pool)), \
         patch("backend.memory.db.get_pool", new=AsyncMock(return_value=mock_pool)), \
         patch("backend.services.chat_stream._schedule_stream_persistence", new=MagicMock()):
        async for sse_item in generate_chat_events(req, mock_request, user_id="user_alice"):
            events.append(sse_item)

    done_events = [e for e in events if '"type": "done"' in e]
    assert len(done_events) == 1
    done_payload = json.loads(done_events[0].replace("data: ", "").strip())
    assert done_payload["skill_used"] == "verify_with_tavily"
    assert "evidence" in done_payload
    assert done_payload["evidence"]["claim_checked"] != "Verify this with Tavily"
    assert "FORGED CONTENT" not in done_payload["evidence"]["claim_checked"]
    assert "Nebius" in done_payload["evidence"]["claim_checked"]


@pytest.mark.asyncio
async def test_chat_stream_conversational_verification_e2e():
    """Phase 7 (2, 3, 5): Conversational 'Verify this with Tavily' resolves from conversation history."""
    import json
    from backend.services.chat_stream import generate_chat_events
    from backend.models import StreamChatRequest

    req = StreamChatRequest(
        message="Verify this with Tavily",
        conversation_id="33333333-3333-3333-3333-333333333333",
    )
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    fake_history = [
        {"role": "user", "content": "When is the Nebius hackathon due?"},
        {
            "role": "assistant",
            "content": "The Nebius x NVIDIA Global AI Hackathon deadline is October 30, 2026 at 1:00 PM EDT.",
        },
    ]

    with patch("backend.services.chat_stream.conversations.get_recent_messages", new=AsyncMock(return_value=fake_history)), \
         patch("backend.services.chat_stream._schedule_stream_persistence", new=MagicMock()):
        events = []
        async for sse_item in generate_chat_events(req, mock_request):
            events.append(sse_item)

    done_events = [e for e in events if '"type": "done"' in e]
    assert len(done_events) == 1
    done_payload = json.loads(done_events[0].replace("data: ", "").strip())
    assert done_payload["skill_used"] == "verify_with_tavily"
    assert "evidence" in done_payload
    assert done_payload["evidence"]["claim_checked"] != "Verify this with Tavily"
    assert "Nebius" in done_payload["evidence"]["claim_checked"]


# ============================================================================
# CLOSE-THE-GAPS VERIFICATION SUITE: FIXES 1 - 6
# ============================================================================

@pytest.mark.asyncio
async def test_server_authoritative_valid_id_with_forged_content_uses_db_content():
    """Fix 1: When target_message_id is present, load message text from DB and IGNORE client content."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "content": "The Nebius x NVIDIA Global AI Hackathon deadline is October 30, 2026 at 1:00 PM EDT."
    }
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    claim, entity = await resolve_verification_claim_and_entity(
        message="Verify this with Tavily",
        target_message_id="42",
        target_message_content="FORGED CONTENT: The deadline is tomorrow morning at 9am.",
        pool=mock_pool,
        user_id="user_alice",
    )
    assert "FORGED" not in claim
    assert "tomorrow morning" not in claim
    assert "Nebius" in claim
    assert "October 30, 2026" in claim


@pytest.mark.asyncio
async def test_server_authoritative_foreign_id_rejected():
    """Fix 1: Cross-tenant / foreign message ID lookup returns empty claim and is rejected."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # DB query returns no row for this tenant
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    claim, entity = await resolve_verification_claim_and_entity(
        message="Verify this with Tavily",
        target_message_id="999",
        target_message_content="Forged claim attempting tenant breakout",
        pool=mock_pool,
        user_id="attacker_user",
    )
    assert claim == ""
    assert entity is None


@pytest.mark.asyncio
async def test_unpersisted_fallback_length_capped_and_control_chars_stripped():
    """Fix 1: Unpersisted message fallback is length-capped at 4000 and control characters stripped."""
    dirty_content = (
        "The Nebius deadline is October 30, 2026.\x00\x08\x0b\x0c\x1b" + ("A" * 5000)
    )
    claim, entity = await resolve_verification_claim_and_entity(
        message="Verify this with Tavily",
        target_message_id=None,
        target_message_content=dirty_content,
    )
    assert "\x00" not in claim
    assert "\x08" not in claim
    assert "\x1b" not in claim
    assert len(claim) <= 4000
    assert "Nebius" in claim


def test_query_sanitization_rules_preserves_topic_words():
    """Fix 2: Strip only instruction phrase; preserve Tavily and verification if part of claim."""
    # Nebius claim query contains no "tavily" / "verify"
    nebius_claim = "The Nebius x NVIDIA Global AI Hackathon submission deadline is October 30, 2026 at 1:00 PM EDT."
    q1 = sanitize_verification_query(nebius_claim)
    assert "tavily" not in q1.lower()
    assert "verify" not in q1.lower()

    # Claim about Tavily itself keeps "Tavily"
    tavily_claim = "Tavily free tier credits"
    q2 = sanitize_verification_query(tavily_claim)
    assert "Tavily" in q2
    assert "credits" in q2

    # Instruction wrapper stripped from Tavily claim while preserving "Tavily"
    q2_wrapped = sanitize_verification_query("Verify this with Tavily: Tavily free tier credits")
    assert "Tavily" in q2_wrapped
    assert "credits" in q2_wrapped

    # Claim with "verification deadline" keeps "verification"
    verif_claim = "verification deadline"
    q3 = sanitize_verification_query(verif_claim)
    assert "verification" in q3
    assert "deadline" in q3

    q3_wrapped = sanitize_verification_query("Verify the verification deadline with Tavily")
    assert "verification deadline" in q3_wrapped.lower()
    assert not q3_wrapped.lower().startswith("verify")


def test_devpost_multi_date_page_no_false_contradiction():
    """Fix 3: Devpost page with start, end, registration, submission dates does not falsely contradict submission deadline."""
    target_claim = "The submission deadline for the Nebius x NVIDIA Global AI Hackathon is October 30, 2026 at 1:00 PM EDT"

    devpost_content = (
        "Registration Opens: August 1, 2026. "
        "Hackathon Kickoff: August 26, 2026. "
        "Submissions close October 30, 2026 at 1:00 PM EDT. "
        "Judging period: November 1, 2026 to November 10, 2026. "
        "Winners Announced: November 15, 2026."
    )
    claims = [
        {"claim": "Registration opens August 1, 2026", "exact_quote": "Registration Opens: August 1, 2026.", "extracted_date": "August 1, 2026", "source_url": "https://nebius.devpost.com"},
        {"claim": "Hackathon kickoff August 26, 2026", "exact_quote": "Hackathon Kickoff: August 26, 2026.", "extracted_date": "August 26, 2026", "source_url": "https://nebius.devpost.com"},
        {"claim": "Submissions close October 30, 2026 at 1:00 PM EDT", "exact_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.", "extracted_date": "October 30, 2026", "source_url": "https://nebius.devpost.com"},
        {"claim": "Winners announced November 15, 2026", "exact_quote": "Winners Announced: November 15, 2026.", "extracted_date": "November 15, 2026", "source_url": "https://nebius.devpost.com"},
    ]
    sources = [{
        "url": "https://nebius.devpost.com",
        "authority_tier": "tier_1_official",
        "authority_badge": "Official Organizer",
        "content": devpost_content,
    }]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=devpost_content,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius.devpost.com": devpost_content},
        target_claim=target_claim,
    )
    assert verdict == "VERIFIED"
    assert verdict != "CONTRADICTED"


def test_deadline_same_date_differing_time_produces_partially_verified():
    """Fix 3: Same date but differing time/timezone yields PARTIALLY_VERIFIED."""
    claim = "The submission deadline for the Nebius hackathon is October 30, 2026 at 1:00 PM EDT"

    # Source specifies same date but 5:00 PM EDT instead of 1:00 PM EDT
    content = "Submissions close October 30, 2026 at 5:00 PM EDT."
    claims = [
        {"claim": "Submissions close October 30, 2026 at 5:00 PM EDT", "exact_quote": "Submissions close October 30, 2026 at 5:00 PM EDT.", "extracted_date": "October 30, 2026", "source_url": "https://nebius.devpost.com"}
    ]
    sources = [{
        "url": "https://nebius.devpost.com",
        "authority_tier": "tier_1_official",
        "authority_badge": "Official Organizer",
        "content": content,
    }]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=content,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius.devpost.com": content},
        target_claim=claim,
    )
    assert verdict == "PARTIALLY_VERIFIED"


def test_deadline_differing_date_produces_contradicted():
    """Fix 3: Primary source with different date for same deadline type yields CONTRADICTED."""
    claim = "The submission deadline for the Nebius hackathon is October 15, 2026 at 1:00 PM EDT"

    content = "Submissions close October 30, 2026 at 1:00 PM EDT."
    claims = [
        {"claim": "Submissions close October 30, 2026 at 1:00 PM EDT", "exact_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.", "extracted_date": "October 30, 2026", "source_url": "https://nebius.devpost.com"}
    ]
    sources = [{
        "url": "https://nebius.devpost.com",
        "authority_tier": "tier_1_official",
        "authority_badge": "Official Organizer",
        "content": content,
    }]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=content,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius.devpost.com": content},
        target_claim=claim,
    )
    assert verdict == "CONTRADICTED"


def test_deadline_no_same_type_date_is_unverified_never_contradicted():
    """Fix 3: If evidence has dates but none match the claim's deadline type, verdict is UNVERIFIED, never CONTRADICTED."""
    claim = "The submission deadline for the Nebius hackathon is October 30, 2026"

    # Evidence only contains registration date
    content = "Registration closes September 1, 2026."
    claims = [
        {"claim": "Registration closes September 1, 2026", "exact_quote": "Registration closes September 1, 2026.", "extracted_date": "September 1, 2026", "source_url": "https://nebius.devpost.com"}
    ]
    sources = [{
        "url": "https://nebius.devpost.com",
        "authority_tier": "tier_1_official",
        "authority_badge": "Official Organizer",
        "content": content,
    }]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=content,
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://nebius.devpost.com": content},
        target_claim=claim,
    )
    assert verdict == "UNVERIFIED"
    assert verdict != "CONTRADICTED"


def test_deadline_multiple_conflicting_dates_same_type_is_conflicting():
    """Fix 3: Multiple conflicting authoritative dates for the same deadline type yield CONFLICTING."""
    claim = "The submission deadline for the Nebius hackathon is October 30, 2026"

    content1 = "Submissions close October 20, 2026 at 1:00 PM EDT."
    content2 = "Submissions close October 30, 2026 at 1:00 PM EDT."
    claims = [
        {"claim": "Submissions close October 20, 2026 at 1:00 PM EDT", "exact_quote": "Submissions close October 20, 2026 at 1:00 PM EDT.", "extracted_date": "October 20, 2026", "source_url": "https://source-a.com/rules"},
        {"claim": "Submissions close October 30, 2026 at 1:00 PM EDT", "exact_quote": "Submissions close October 30, 2026 at 1:00 PM EDT.", "extracted_date": "October 30, 2026", "source_url": "https://source-b.com/rules"},
    ]
    sources = [
        {"url": "https://source-a.com/rules", "authority_tier": "tier_1_official", "authority_badge": "Official Organizer", "content": content1},
        {"url": "https://source-b.com/rules", "authority_tier": "tier_1_official", "authority_badge": "Official Organizer", "content": content2},
    ]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=f"{content1} {content2}",
        sources=sources,
        target_entity="Nebius",
        source_text_map={"https://source-a.com/rules": content1, "https://source-b.com/rules": content2},
        target_claim=claim,
    )
    assert verdict == "CONFLICTING"


def test_deadline_past_date_is_stale_against_runtime_clock():
    """Fix 3: When the verified deadline has already passed, verdict is STALE."""
    claim = "The hackathon submission deadline is January 15, 2020 at 1:00 PM EDT"

    content = "Submissions close January 15, 2020 at 1:00 PM EDT."
    claims = [
        {"claim": "Submissions close January 15, 2020 at 1:00 PM EDT", "exact_quote": "Submissions close January 15, 2020 at 1:00 PM EDT.", "extracted_date": "January 15, 2020", "source_url": "https://past-event.com/rules"}
    ]
    sources = [{
        "url": "https://past-event.com/rules",
        "authority_tier": "tier_1_official",
        "authority_badge": "Official Organizer",
        "content": content,
    }]

    verdict, items = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=content,
        sources=sources,
        target_entity="Hackathon",
        source_text_map={"https://past-event.com/rules": content},
        target_claim=claim,
    )
    assert verdict == "STALE"


@pytest.mark.asyncio
async def test_truncation_detection_and_no_fake_closing_markdown():
    """Fix 4: When output budget hits length limit, detect is_truncated=True and do not fake completeness with markdown."""
    from backend.agent_synthesis import force_final_synthesis
    from backend.config import Settings

    settings = Settings()
    settings.MAX_CONTINUATION_ATTEMPTS = 0  # Test raw truncation without continuation

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "length"
    mock_choice.message.content = "Here is the comprehensive roadmap for the project up to step 4."
    mock_resp.choices = [mock_choice]
    mock_resp.usage = MagicMock(prompt_tokens=400, completion_tokens=1024)

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(return_value=mock_resp)
    mock_client = MagicMock()
    mock_client.chat.completions = mock_completions

    step, cost, abstained = await force_final_synthesis(
        client=mock_client,
        settings=settings,
        messages=[{"role": "user", "content": "Create a roadmap"}],
        step_num=3,
        start_time=0.0,
        run_id="run-trunc-test",
        active_replan_diff=None,
    )

    assert step.metadata is not None
    assert step.metadata["is_truncated"] is True
    assert step.metadata["finish_reason"] == "length"
    # Ensure no fake closing markdown note was appended
    assert "*[Note: Response reached maximum token budget; generation concluded.]*" not in step.content
    assert step.content.startswith("Here is the comprehensive roadmap")


@pytest.mark.asyncio
async def test_bounded_continuation_preserves_text_without_duplication():
    """Fix 4: Bounded continuation (up to 2 attempts) continues exactly where left off without duplicated text."""
    from backend.agent_synthesis import force_final_synthesis
    from backend.config import Settings

    settings = Settings()
    settings.MAX_CONTINUATION_ATTEMPTS = 2

    # First call: truncated with length limit
    mock_resp_1 = MagicMock()
    mock_choice_1 = MagicMock()
    mock_choice_1.finish_reason = "length"
    mock_choice_1.message.content = "Step 1: Planning\nStep 2: Architecture"
    mock_resp_1.choices = [mock_choice_1]
    mock_resp_1.usage = MagicMock(prompt_tokens=200, completion_tokens=100)

    # Second call (continuation): completed with stop
    mock_resp_2 = MagicMock()
    mock_choice_2 = MagicMock()
    mock_choice_2.finish_reason = "stop"
    mock_choice_2.message.content = "Step 3: Implementation\nStep 4: Verification"
    mock_resp_2.choices = [mock_choice_2]
    mock_resp_2.usage = MagicMock(prompt_tokens=300, completion_tokens=100)

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(side_effect=[mock_resp_1, mock_resp_2])
    mock_client = MagicMock()
    mock_client.chat.completions = mock_completions

    step, cost, abstained = await force_final_synthesis(
        client=mock_client,
        settings=settings,
        messages=[{"role": "user", "content": "Create a roadmap"}],
        step_num=3,
        start_time=0.0,
        run_id="run-cont-test",
        active_replan_diff=None,
    )

    assert step.metadata is not None
    assert step.metadata["is_truncated"] is False
    assert step.metadata["continuation_attempts"] == 1
    assert "Step 1: Planning" in step.content
    assert "Step 2: Architecture" in step.content
    assert "Step 3: Implementation" in step.content
    assert "Step 4: Verification" in step.content
    # No duplicate headings
    assert step.content.count("Step 1: Planning") == 1
    assert step.content.count("Step 3: Implementation") == 1


@pytest.mark.asyncio
async def test_ambiguity_no_antecedent_zero_calls_zero_credits():
    """Fix 5: 'Verify this' with no antecedent asks concise clarification with 0 tool calls and 0 credits."""
    from backend.router import route_message

    skill, args, text_reply = await route_message(
        message="Verify this with Tavily",
        history=[],
    )
    # Must NOT dispatch to verify_with_tavily
    assert skill is None
    assert args is None
    assert "couldn't find a specific claim" in text_reply.lower()


def test_tavily_usage_cap_constants():
    """Fix 5: Enforce and verify Tavily usage cap constants in code."""
    from backend.config import Settings
    from backend.services.budgets import (
        MAX_RUN_TAVILY_CREDITS,
        MAX_DAILY_USER_TAVILY_CREDITS,
        MAX_DAILY_GUEST_TAVILY_CREDITS,
    )

    settings = Settings()
    assert settings.GLOBAL_DAILY_TAVILY_CREDIT_CAP == 100
    assert MAX_RUN_TAVILY_CREDITS == 6
    assert MAX_DAILY_USER_TAVILY_CREDITS == 30
    assert MAX_DAILY_GUEST_TAVILY_CREDITS == 25


