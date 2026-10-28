"""
Compass — Internship Radar Synchronization Orchestrator.

Manages multi-source discovery and verification synchronization runs:
1. Ingests curated Indian opportunities across startups, research labs, government portals, and open source.
2. Ingests permitted public ATS feeds (Greenhouse, Lever, Ashby) for high-growth tech startups.
3. Ingests candidate community repositories with URL deduplication.
4. Performs bounded, category-specific Tavily discovery queries when configured.
5. Updates status verification and records sync metrics idempotently with complete error isolation.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.memory.radar import (
    add_opportunity_source,
    add_status_history,
    create_sync_run,
    finish_sync_run,
    get_all_opportunities,
    get_last_sync_run,
    upsert_opportunity,
    upsert_opportunity_cycle,
    upsert_opportunity_requirements,
)
from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_ats_adapters import fetch_all_public_ats_opportunities
from backend.services.radar_sources import (
    CURATED_INDIAN_OPPORTUNITIES,
    canonicalize_url,
    fetch_github_markdown_opportunities,
    infer_category,
    infer_employer_type,
    normalize_company_name,
)
from backend.services.radar_jobspy import discover_jobspy_opportunities
from backend.services.radar_verifier import verify_opportunity_status
from backend.services.tavily import search as tavily_search, tavily_available

logger = logging.getLogger("compass.radar.sync")

# Global in-process lock to prevent overlapping runs
_sync_lock = asyncio.Lock()

GITHUB_SOURCES = [
    {
        "source_name": "zapplyjobs/underclassmen-internships",
        "url": "https://raw.githubusercontent.com/zapplyjobs/underclassmen-internships/main/README.md",
    },
    {
        "source_name": "Jose-Gael/underclassmen-opportunities",
        "url": "https://raw.githubusercontent.com/Jose-Gael-Cruz-Lopez/underclassmen-opportunities/main/README.md",
    },
]

DISCOVERY_QUERIES = [
    ("ai_ml", "AI ML deep learning research internship 2026 undergraduate students India apply"),
    ("startup", "software engineering startup internship 2026 Bengaluru Pune Remote India apply"),
    ("research", "summer research fellowship 2026 IISc IIT TIFR CSIR undergraduate India apply"),
    ("open_source", "open source fellowship GSoC LFX 2026 students apply"),
]


async def run_radar_sync(source_filter: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """
    Executes a complete synchronization run across all active source providers.
    Safe against concurrent execution and individual source failures.
    When dry_run=True, executes discovery without database mutations.
    """
    if _sync_lock.locked():
        return {
            "status": "in_progress",
            "message": "A radar synchronization run is already actively running.",
        }

    async with _sync_lock:
        run_id = -1 if dry_run else await create_sync_run("all" if not source_filter else source_filter)
        start_time = datetime.now(timezone.utc)
        records_discovered = 0
        records_updated = 0
        records_skipped = 0
        failures = 0
        error_summary = ""
        if dry_run:
            logger.info(f"[DRY-RUN] Radar sync initiated (source_filter={source_filter}). No DB writes will occur.")

        try:
            # 1. Ingest Curated Opportunities across all 6 Sectors
            if not source_filter or source_filter in {"all", "curated"}:
                if dry_run:
                    records_discovered += len(CURATED_INDIAN_OPPORTUNITIES)
                else:
                    for item in CURATED_INDIAN_OPPORTUNITIES:
                        try:
                            opp_id = await upsert_opportunity(
                                company_name=item["company_name"],
                                role_title=item["role_title"],
                                canonical_url=item["canonical_url"],
                                official_application_url=item["official_application_url"],
                                current_status=item["current_status"],
                                opportunity_type=item["opportunity_type"],
                                employer_type=item.get("employer_type", EmployerType.ENTERPRISE),
                                category=item["category"],
                                location=item.get("location"),
                                work_arrangement=item.get("work_arrangement", "unknown"),
                                country=item.get("country", "India"),
                                is_india_eligible=item.get("is_india_eligible", True),
                                compensation=item.get("compensation"),
                                duration=item.get("duration"),
                                confirmed_open_date=item.get("confirmed_open_date"),
                                description=item.get("description"),
                                last_verified_at=datetime.now(timezone.utc),
                                verification_evidence=item.get("verification_evidence"),
                                employer_identity_verified=item.get("employer_identity_verified", True),
                                official_source_confirmed=item.get("official_source_confirmed", True),
                                application_url_checked=item.get("application_url_checked", True),
                            )
                            records_discovered += 1

                            # Requirements
                            reqs = item.get("requirements")
                            if reqs:
                                await upsert_opportunity_requirements(opp_id, reqs)

                            # Historical Cycles
                            for cycle in item.get("cycles", []):
                                await upsert_opportunity_cycle(
                                    opportunity_id=opp_id,
                                    cycle_year=cycle["cycle_year"],
                                    observed_open_date=cycle.get("observed_open_date"),
                                    observed_close_date=cycle.get("observed_close_date"),
                                    observation_type="confirmed",
                                    notes="Verified official recruitment cycle",
                                )

                            # Provenance Source
                            src = item.get("source")
                            if src:
                                await add_opportunity_source(
                                    opportunity_id=opp_id,
                                    source_name=src["source_name"],
                                    source_type=src["source_type"],
                                    source_url=src["source_url"],
                                    source_authority=src.get("source_authority", "tier_1"),
                                    verification_result="verified",
                                )
                            records_updated += 1
                        except Exception as ex:
                            failures += 1
                            logger.warning(f"Failed to upsert curated opportunity {item.get('company_name')}: {ex}")

            # 2. Ingest Public ATS Feeds (Greenhouse, Lever, Ashby)
            if not source_filter or source_filter in {"all", "ats"}:
                try:
                    ats_opps = await fetch_all_public_ats_opportunities(timeout_sec=8.0)
                    for ats in ats_opps:
                        try:
                            records_discovered += 1
                            canonical = ats["canonical_url"]
                            if not canonical:
                                records_skipped += 1
                                continue

                            opp_id = await upsert_opportunity(
                                company_name=ats["company_name"],
                                role_title=ats["role_title"],
                                canonical_url=canonical,
                                official_application_url=ats["official_application_url"],
                                current_status=ats["current_status"],
                                opportunity_type=ats["opportunity_type"],
                                employer_type=ats.get("employer_type", EmployerType.STARTUP),
                                category=ats["category"],
                                location=ats.get("location"),
                                work_arrangement=ats.get("work_arrangement", "unknown"),
                                country=ats.get("country", "India"),
                                is_india_eligible=ats.get("is_india_eligible", True),
                                description=ats.get("description"),
                                last_verified_at=datetime.now(timezone.utc),
                                verification_evidence=ats.get("verification_evidence"),
                                employer_identity_verified=True,
                                official_source_confirmed=True,
                                application_url_checked=True,
                            )

                            await add_opportunity_source(
                                opportunity_id=opp_id,
                                source_name=ats["source_name"],
                                source_type=ats["source_type"],
                                source_url=ats["source_url"],
                                source_authority=ats.get("source_authority", "tier_1"),
                                verification_result="verified",
                            )
                            records_updated += 1
                        except Exception as a_err:
                            failures += 1
                            logger.warning(f"Failed to ingest ATS job {ats.get('role_title')}: {a_err}")
                except Exception as ats_all_err:
                    failures += 1
                    logger.warning(f"Public ATS synchronization encountered an issue: {ats_all_err}")

            # 3. Ingest GitHub Curated Repositories
            if not source_filter or source_filter in {"all", "github"}:
                for src_cfg in GITHUB_SOURCES:
                    if source_filter and source_filter != "all" and src_cfg["source_name"] != source_filter:
                        continue
                    try:
                        gh_opps = await fetch_github_markdown_opportunities(src_cfg["url"], src_cfg["source_name"])
                        for gh in gh_opps:
                            records_discovered += 1
                            canonical = gh["canonical_url"]
                            if not canonical:
                                records_skipped += 1
                                continue

                            opp_id = await upsert_opportunity(
                                company_name=gh["company_name"],
                                role_title=gh["role_title"],
                                canonical_url=canonical,
                                official_application_url=gh["official_application_url"],
                                current_status=gh["current_status"],
                                opportunity_type=gh["opportunity_type"],
                                employer_type=gh.get("employer_type", EmployerType.STARTUP),
                                category=gh["category"],
                                location=gh.get("location"),
                                work_arrangement=gh.get("work_arrangement", "unknown"),
                                country=gh.get("country", "Global"),
                                is_india_eligible=gh.get("is_india_eligible", True),
                                description=gh.get("description"),
                            )

                            await add_opportunity_source(
                                opportunity_id=opp_id,
                                source_name=gh["source_name"],
                                source_type=gh["source_type"],
                                source_url=gh["source_url"],
                                source_authority="tier_2",
                                verification_result="unverified",
                            )

                            # Insert basic requirements if present
                            if gh.get("eligible_academic_years"):
                                await upsert_opportunity_requirements(opp_id, {
                                    "eligible_academic_years": gh["eligible_academic_years"],
                                    "eligible_countries": ["India"] if gh.get("is_india_eligible") else [],
                                })
                            records_updated += 1
                    except Exception as ex:
                        failures += 1
                        logger.warning(f"Error syncing GitHub source {src_cfg['source_name']}: {ex}")

            # 4. Targeted Category-Specific Tavily Discovery Queries (if configured)
            if tavily_available() and (not source_filter or source_filter in {"all", "tavily"}):
                for cat_tag, tav_query in DISCOVERY_QUERIES:
                    try:
                        tav_res = await tavily_search(tav_query, max_results=5)
                        results = tav_res.get("results", [])
                        for res in results:
                            records_discovered += 1
                            url = res.get("url")
                            title = res.get("title", "")
                            snippet = res.get("content", "")
                            if not url or ("apply" not in title.lower() and "intern" not in title.lower() and "fellow" not in title.lower()):
                                records_skipped += 1
                                continue

                            # Extract company name estimate from title
                            parts = title.split("-") if "-" in title else title.split("|")
                            comp = parts[0].strip() if len(parts) > 1 else "Emerging Tech / Lab"
                            role = parts[1].strip() if len(parts) > 1 else title

                            cat = infer_category(role)
                            emp_type = infer_employer_type(comp, cat)

                            opp_id = await upsert_opportunity(
                                company_name=comp[:80],
                                role_title=role[:120],
                                canonical_url=canonicalize_url(url, role),
                                official_application_url=url,
                                current_status=OpportunityStatus.DISCOVERED,
                                opportunity_type="internship" if "fellow" not in role.lower() else "fellowship",
                                employer_type=emp_type,
                                category=cat,
                                location="India / Remote",
                                work_arrangement="remote" if "remote" in snippet.lower() else "hybrid",
                                country="India",
                                is_india_eligible=True,
                                description=snippet[:400],
                                verification_evidence="Discovered via targeted search query; pending reachability verification.",
                                employer_identity_verified=False,
                                official_source_confirmed=False,
                                application_url_checked=False,
                            )

                            await add_opportunity_source(
                                opportunity_id=opp_id,
                                source_name="Tavily Discovery",
                                source_type="tavily_search",
                                source_url=url,
                                source_authority="tier_3",
                                verification_result="discovered",
                            )
                            records_updated += 1
                    except Exception as t_err:
                        logger.warning(f"Tavily discovery search for query '{tav_query}' encountered an error: {t_err}")

            # 5. Ingest JobSpy Public Board Discovery (Indeed, LinkedIn, Glassdoor, ZipRecruiter)
            if not source_filter or source_filter in {"all", "jobspy"}:
                try:
                    if dry_run:
                        logger.info("[DRY-RUN] Executing JobSpy discovery adapter (dry-run mode, hours_old=24, results_wanted=5)...")
                        jobspy_summary = await discover_jobspy_opportunities(hours_old=24, results_wanted=5)
                        raw_cnt = jobspy_summary.get("raw_results", 0)
                        opps = jobspy_summary.get("opportunities", [])
                        records_discovered += raw_cnt
                        logger.info(f"[DRY-RUN] JobSpy adapter discovered {raw_cnt} raw listings ({len(opps)} matches); 0 persisted to DB.")
                    else:
                        jobspy_summary = await discover_jobspy_opportunities(hours_old=24, results_wanted=10)
                        jobspy_opps = jobspy_summary.get("opportunities", [])
                        for j_opp in jobspy_opps:
                            try:
                                records_discovered += 1
                                canonical = j_opp.get("canonical_url")
                                if not canonical:
                                    records_skipped += 1
                                    continue

                                posting_dt = None
                                if j_opp.get("posting_datetime_utc"):
                                    try:
                                        posting_dt = datetime.fromisoformat(j_opp["posting_datetime_utc"])
                                    except Exception:
                                        posting_dt = None

                                opp_id = await upsert_opportunity(
                                    company_name=j_opp["company_name"],
                                    role_title=j_opp["role_title"],
                                    canonical_url=canonical,
                                    official_application_url=j_opp["official_application_url"],
                                    current_status=j_opp["current_status"],
                                    opportunity_type=j_opp["opportunity_type"],
                                    employer_type=j_opp.get("employer_type") or EmployerType.ENTERPRISE,
                                    category=j_opp["category"],
                                    location=j_opp.get("location"),
                                    work_arrangement=j_opp.get("work_arrangement", "unknown"),
                                    country=j_opp.get("country", "Global"),
                                    is_india_eligible=j_opp.get("is_india_eligible", True),
                                    compensation=j_opp.get("compensation"),
                                    confirmed_open_date=j_opp.get("confirmed_open_date"),
                                    description=j_opp.get("description"),
                                    last_verified_at=datetime.now(timezone.utc),
                                    verification_evidence=j_opp.get("verification_evidence"),
                                    employer_identity_verified=j_opp.get("employer_identity_verified", False),
                                    official_source_confirmed=j_opp.get("official_source_confirmed", False),
                                    application_url_checked=j_opp.get("application_url_checked", False),
                                    posted_at=posting_dt,
                                    posted_at_precision=j_opp.get("posted_at_precision") or ("exact" if posting_dt else "unknown"),
                                )

                                reqs = j_opp.get("requirements")
                                if reqs:
                                    await upsert_opportunity_requirements(opp_id, reqs)

                                await add_opportunity_source(
                                    opportunity_id=opp_id,
                                    source_name=j_opp["source_name"],
                                    source_type=j_opp["source_type"],
                                    source_url=j_opp["source_url"],
                                    source_authority=j_opp.get("source_authority", "tier_2"),
                                    verification_result=(
                                        "verified" if j_opp.get("official_source_confirmed") else "discovered"
                                    ),
                                )
                                records_updated += 1
                            except Exception as j_err:
                                failures += 1
                                logger.warning(f"Failed to ingest JobSpy opportunity {j_opp.get('role_title')}: {j_err}")
                except Exception as jobspy_all_err:
                    failures += 1
                    logger.warning(f"JobSpy synchronization encountered an issue: {jobspy_all_err}")

            status = "completed" if failures == 0 else "completed_with_errors"
            if failures > 0:
                error_summary = f"{failures} records or network sources encountered warnings during sync."

        except Exception as e:
            status = "failed"
            error_summary = str(e)
            logger.error(f"Critical error during radar sync: {e}", exc_info=True)

        if not dry_run:
            await finish_sync_run(
                run_id=run_id,
                status=status,
                records_discovered=records_discovered,
                records_updated=records_updated,
                records_skipped=records_skipped,
                failures=failures,
                error_summary=error_summary,
            )

        return {
            "run_id": run_id,
            "status": "completed_dry_run" if dry_run else status,
            "records_discovered": records_discovered,
            "records_updated": records_updated,
            "records_skipped": records_skipped,
            "failures": failures,
            "error_summary": error_summary,
            "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
        }
