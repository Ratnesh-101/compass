"""
Compass — Real Tavily Verification Pipeline Demo.

Runs the real deadline verification pipeline with evidence ledger rows for:
  Run (i):   VERIFIED: Stored deadline matches official source with explicit year.
  Run (ii):  CHANGED: Stored deadline has schedule drift against updated official date.
  Run (iii): ACTUAL SUBMISSION HACKATHON: Nebius x NVIDIA Global AI Hackathon.
             Performs live web audit via Tavily and evaluates official event-page binding.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
import sys
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.services import tavily
from backend.services.tavily_deadline import analyze_deadline_drift
from backend.services.tavily_authority import classify_domain_authority


def format_ledger_row(
    claim: str,
    verbatim_quote: str,
    parsed_date: str,
    year_provenance: str,
    source_url: str,
    tier: str,
    retrieved_at: str,
    credits_used: int,
) -> str:
    lines = [
        f"  * Claim:                {claim}",
        f"  * Verbatim Quote:       \"{verbatim_quote.strip()}\"",
        f"  * Parsed Date:          {parsed_date} (Year provenance: {year_provenance})",
        f"  * Source URL:           {source_url}",
        f"  * Authority Tier:       {tier}",
        f"  * Retrieved At:         {retrieved_at}",
        f"  * Tavily Credits Used:  {credits_used}",
    ]
    return "\n".join(lines)


async def run_pipeline():
    print("=" * 80)
    print("COMPASS — EVIDENCE LEDGER & DEADLINE VERIFICATION PIPELINE DEMO")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # RUN (i): VERIFIED (Recorded Ground-Truth Benchmark Fixture)
    # -------------------------------------------------------------------------
    run_id_1 = f"run-verified-{uuid.uuid4().hex[:8]}"
    retrieved_at_1 = datetime.now(timezone.utc).isoformat()
    claim_1 = "Submit Chroma Awards official entry by Nov 17, 2026"
    quote_1 = "All submissions must be uploaded by November 17, 2026 at 11:59pm PT. Late submissions will not be accepted."
    url_1 = "https://chromaawards.devpost.com/rules"
    auth_1 = classify_domain_authority(
        url_1,
        target_entity="Chroma Awards",
        pinned_event_prefixes=["https://chromaawards.devpost.com"],
    )
    raw_results_1 = [
        {
            "url": url_1,
            "title": "Chroma Awards 2026 Official Rules and Eligibility",
            "content": quote_1,
            "authority_tier": auth_1["tier"],
            "authority_badge": auth_1["badge"],
            "authority_weight": auth_1["weight"],
        }
    ]
    stored_due_1 = "2026-11-17"
    drift_1 = analyze_deadline_drift(stored_due_1, raw_results_1)

    print("\n[RUN I: VERIFIED (RECORDED BENCHMARK FIXTURE)]")
    print(f"Run ID: {run_id_1}")
    print("Evidence Ledger:")
    print(
        format_ledger_row(
            claim=claim_1,
            verbatim_quote=quote_1,
            parsed_date=drift_1.get("live_date") or "None",
            year_provenance=drift_1.get("year_provenance") or "explicit_in_quote",
            source_url=url_1,
            tier=auth_1["tier"],
            retrieved_at=retrieved_at_1,
            credits_used=0,
        )
    )
    print("Pipeline Output:")
    print(f"  * Verdict:        {drift_1['verdict']}")
    print(f"  * Drift Verdict:  {drift_1['drift_verdict']}")
    print(f"  * Has Drift:      {drift_1['has_drift']}")
    print(f"  * Drift Days:     {drift_1['drift_days']}")
    print(f"  * Recommendation: {drift_1['recommendation']}")

    # -------------------------------------------------------------------------
    # RUN (ii): CHANGED (Recorded Ground-Truth Schedule Extension Fixture)
    # -------------------------------------------------------------------------
    run_id_2 = f"run-changed-{uuid.uuid4().hex[:8]}"
    retrieved_at_2 = datetime.now(timezone.utc).isoformat()
    claim_2 = "Stored task deadline is 2026-11-01, checking official extension"
    stored_due_2 = "2026-11-01"
    quote_2 = "Update: Final submission deadline extended to November 17, 2026 at 11:59pm PT."
    raw_results_2 = [
        {
            "url": url_1,
            "title": "Chroma Awards 2026 Official Rules and Eligibility - Deadline Update",
            "content": quote_2,
            "authority_tier": auth_1["tier"],
            "authority_badge": auth_1["badge"],
            "authority_weight": auth_1["weight"],
        }
    ]
    drift_2 = analyze_deadline_drift(stored_due_2, raw_results_2)

    print("\n[RUN II: CHANGED (RECORDED BENCHMARK FIXTURE)]")
    print(f"Run ID: {run_id_2}")
    print("Evidence Ledger:")
    print(
        format_ledger_row(
            claim=claim_2,
            verbatim_quote=quote_2,
            parsed_date=drift_2.get("live_date") or "None",
            year_provenance=drift_2.get("year_provenance") or "explicit_in_quote",
            source_url=url_1,
            tier=auth_1["tier"],
            retrieved_at=retrieved_at_2,
            credits_used=0,
        )
    )
    print("Pipeline Output:")
    print(f"  * Verdict:        {drift_2['verdict']}")
    print(f"  * Drift Verdict:  {drift_2['drift_verdict']}")
    print(f"  * Has Drift:      {drift_2['has_drift']}")
    print(f"  * Drift Days:     {drift_2['drift_days']} ({drift_2['direction']})")
    print(f"  * Recommendation: {drift_2['recommendation']}")

    # -------------------------------------------------------------------------
    # RUN (iii): ACTUAL SUBMISSION HACKATHON (Nebius x NVIDIA — LIVE TAVILY QUERY)
    # -------------------------------------------------------------------------
    run_id_3 = f"run-nebius-{uuid.uuid4().hex[:8]}"
    retrieved_at_3 = datetime.now(timezone.utc).isoformat()
    query_3 = "nebiusglobalaihackathon devpost rules submission deadline"
    claim_3 = "Submit entry to Nebius x NVIDIA Global AI Hackathon"
    stored_due_3 = "2026-10-30"

    credits_used_3 = 0
    raw_search = None
    if tavily.tavily_available():
        try:
            raw_search = await tavily.search(
                query_3,
                max_results=5,
                include_domains=["nebiusglobalaihackathon.devpost.com"],
            )
            credits_used_3 = 1
        except Exception as e:
            print(f"Tavily live search exception: {e}")

    results_3 = raw_search.get("results", []) if isinstance(raw_search, dict) else (raw_search or [])

    # Classify each retrieved search result using strict event-page authority rule
    classified_results_3 = []
    for r in results_3:
        url = r.get("url", "")
        auth = classify_domain_authority(
            url,
            target_entity="Nebius x NVIDIA",
            pinned_event_prefixes=["https://nebiusglobalaihackathon.devpost.com"],
        )
        r_copy = dict(r)
        r_copy["authority_tier"] = auth["tier"]
        r_copy["authority_badge"] = auth["badge"]
        r_copy["authority_weight"] = auth["weight"]
        classified_results_3.append(r_copy)

    drift_3 = analyze_deadline_drift(stored_due_3, classified_results_3)
    top_candidate = classified_results_3[0] if classified_results_3 else {}
    top_evidence_3 = drift_3.get("evidence") or top_candidate.get("content", "No evidence retrieved")
    top_url_3 = drift_3.get("source_url") or top_candidate.get("url", "N/A")
    top_tier_3 = top_candidate.get("authority_tier", "tier_3_general")

    print("\n[RUN III: NEBIUS x NVIDIA GLOBAL AI HACKATHON (LIVE TAVILY RUN)]")
    print(f"Run ID: {run_id_3}")
    print(f"Live Query Executed: '{query_3}'")
    print(f"Results Retrieved: {len(classified_results_3)}")
    print("Evidence Ledger:")
    print(
        format_ledger_row(
            claim=claim_3,
            verbatim_quote=top_evidence_3[:250],
            parsed_date=drift_3.get("live_date") or "NOT_FOUND",
            year_provenance=drift_3.get("year_provenance") or "explicit_in_quote",
            source_url=top_url_3,
            tier=top_tier_3,
            retrieved_at=retrieved_at_3,
            credits_used=credits_used_3,
        )
    )
    print("Pipeline Output:")
    print(f"  * Stored Due Date:    {stored_due_3}")
    print(f"  * Detected Live Date: {drift_3.get('live_date')}")
    print(f"  * Verdict:            {drift_3['verdict']}")
    print(f"  * Drift Verdict:      {drift_3['drift_verdict']}")
    print(f"  * Has Drift:          {drift_3['has_drift']}")
    print(f"  * Recommendation:     {drift_3['recommendation']}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
