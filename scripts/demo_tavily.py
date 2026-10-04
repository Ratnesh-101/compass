"""
Compass — Tavily Deep Research Demo & Evidence Ledger Inspection.

Executes a live end-to-end research and deadline verification query,
demonstrating query decomposition, official domain ranking, verbatim quote
validation, and deterministic verdict derivation. Prints the Evidence Ledger.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.tavily_pipeline import run_tavily_research
from backend.services.tavily import tavily_available


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 80)
    print("COMPASS - TAVILY DEEP RESEARCH PIPELINE DEMO")
    print("=" * 80)

    if not tavily_available():
        print("[!] Tavily API is not configured or disabled in settings.")
        print("Set TAVILY_API_KEY in your environment to run against the live Tavily API.")
        print("Simulating research pipeline execution...")

    query = "Nebius AI Studio hackathon submission deadline rules"
    print(f"\n🔍 Research Objective: '{query}'")
    print("Executing query decomposition, official source retrieval, and evidence extraction...\n")

    res = await run_tavily_research(query, include_domains=["nebius.com", "devpost.com"], target_entity="Nebius AI Studio")

    print("-" * 80)
    print(f"VERDICT:  {res.get('verdict')}")
    print(f"SUMMARY:  {res.get('summary')}")
    print(f"RUN ID:   {res.get('run_id')}")
    print("-" * 80)

    print("\n[+] EVIDENCE LEDGER:")
    ledger = res.get("evidence_ledger", [])
    if not ledger:
        print("  (No evidence ledger entries generated)")
    else:
        for idx, item in enumerate(ledger, 1):
            print(f"\n[{idx}] CLAIM: {item.get('claim')}")
            print(f"    Source URL:    {item.get('source_url')}")
            print(f"    Authority:     {item.get('authority_tier')}")
            print(f"    Verbatim Text: \"{item.get('verbatim_quote')}\"")
            print(f"    Verified Match:{item.get('verbatim_verified')}")
            print(f"    Verdict:       {item.get('verdict')}")
            print(f"    Timestamp:     {item.get('retrieved_at')}")

    print("\n[*] DISCOVERED SOURCES:")
    for s in res.get("sources", []):
        print(f"  - [{s.get('authority_badge')}] {s.get('domain')} - {s.get('url')}")

    print("\n" + "=" * 80)
    print("[OK] Tavily Deep Research Pipeline execution complete.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
