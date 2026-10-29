"""
Compass - Company Intelligence Background Job & Resilient Fallback Service.

Provides:
  - Asynchronous refresh job queue with in-memory thread-safe tracking.
  - Job expiry and single-job-per-opportunity concurrency guard.
  - Structured stage telemetry logging (zero secrets, zero full texts).
  - Resilient "sources-only" fallback brief when LLM is unavailable.
  - "From the job posting" fallback brief when web search is unavailable.
  - Safe, standardized machine-readable failure reason codes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
import uuid

logger = logging.getLogger("compass.services.company_intel_jobs")

SCHEMA_VERSION = "2.0"
JOB_TTL_SECONDS = 300.0  # 5 minutes maximum job lifetime

# In-memory job registry: job_id -> job dict
_JOBS: Dict[str, Dict[str, Any]] = {}
# Active job mapping: opportunity_id -> job_id
_ACTIVE_OPP_JOBS: Dict[int, str] = {}
_JOBS_LOCK = asyncio.Lock()


def log_intel_stage(
    stage: str,
    opportunity_id: int,
    company: str,
    details: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
    error_class: Optional[str] = None,
) -> None:
    """Server-side structured logger for company intel pipeline stages.

    Logs counts, durations, and error classes ONLY.
    Strictly forbids printing API keys, authorization tokens, or raw scraped texts.
    """
    safe_details = {}
    if details:
        for k, v in details.items():
            if k in ("count", "result_count", "subqueries_count", "tokens", "status", "reason", "schema_version"):
                safe_details[k] = v
            elif isinstance(v, (int, float, bool)):
                safe_details[k] = v

    dur_str = f" duration_ms={duration_ms}" if duration_ms is not None else ""
    err_str = f" error_class={error_class}" if error_class else ""
    extra_str = f" details={safe_details}" if safe_details else ""
    logger.info(
        f"[COMPANY_INTEL_STAGE] stage={stage} opp_id={opportunity_id} company={company[:30]}"
        f"{dur_str}{err_str}{extra_str}"
    )


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve job metadata by job_id, auto-pruning expired jobs."""
    async with _JOBS_LOCK:
        _prune_expired_jobs_locked()
        job = _JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


async def get_active_job_for_opportunity(opp_id: int) -> Optional[Dict[str, Any]]:
    """Return running or queued job for opportunity if one exists."""
    async with _JOBS_LOCK:
        _prune_expired_jobs_locked()
        job_id = _ACTIVE_OPP_JOBS.get(opp_id)
        if not job_id:
            return None
        job = _JOBS.get(job_id)
        if job and job.get("status") in ("queued", "running"):
            return dict(job)
        return None


async def create_job(opp_id: int, company: str, role: str) -> Dict[str, Any]:
    """Create a new tracked background job for opportunity intel refresh."""
    async with _JOBS_LOCK:
        _prune_expired_jobs_locked()
        # Concurrency guard: reuse active job if currently queued/running
        existing_id = _ACTIVE_OPP_JOBS.get(opp_id)
        if existing_id and existing_id in _JOBS:
            existing = _JOBS[existing_id]
            if existing.get("status") in ("queued", "running"):
                return dict(existing)

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        job = {
            "job_id": job_id,
            "opportunity_id": opp_id,
            "company": company,
            "role": role,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + JOB_TTL_SECONDS,
            "result": None,
            "error": None,
            "reason": None,
            "message": None,
            "schema_version": SCHEMA_VERSION,
        }
        _JOBS[job_id] = job
        _ACTIVE_OPP_JOBS[opp_id] = job_id
        return dict(job)


async def update_job(
    job_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    reason: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """Update job status and results."""
    async with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = status
        job["updated_at"] = time.time()
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        if reason is not None:
            job["reason"] = reason
        if message is not None:
            job["message"] = message

        if status in ("done", "failed"):
            opp_id = job.get("opportunity_id")
            if opp_id and _ACTIVE_OPP_JOBS.get(opp_id) == job_id:
                _ACTIVE_OPP_JOBS.pop(opp_id, None)


def _prune_expired_jobs_locked() -> None:
    now = time.time()
    expired = [jid for jid, j in _JOBS.items() if j.get("expires_at", 0) < now]
    for jid in expired:
        opp_id = _JOBS[jid].get("opportunity_id")
        if opp_id and _ACTIVE_OPP_JOBS.get(opp_id) == jid:
            _ACTIVE_OPP_JOBS.pop(opp_id, None)
        _JOBS.pop(jid, None)


def build_sources_only_fallback(
    cleaned_sources: List[Dict[str, Any]],
    company: str,
    role: str,
    reason: str = "model_failed",
) -> Dict[str, Any]:
    """Construct a clean, non-error fallback brief when sources exist but LLM fails."""
    priorities: List[Dict[str, Any]] = []
    challenges: List[Dict[str, Any]] = []
    role_context: List[Dict[str, Any]] = []

    for s in cleaned_sources[:4]:
        snippet = s.get("snippet", "")
        # Extract first complete sentence
        match = re.search(r"([^.!?]+[.!?])", snippet)
        sentence = match.group(1).strip() if match else snippet.split("\n")[0].strip()
        words = sentence.split()
        if len(words) > 22:
            sentence = " ".join(words[:22]).rstrip(".,;:") + "."
        elif not sentence.endswith((".", "!", "?")):
            sentence += "."
        sentence = sentence.replace("—", "-").replace("–", "-")

        point_entry = {"point": sentence, "source": s["id"]}
        lower = snippet.lower()
        if any(k in lower for k in ("challenge", "problem", "scaling", "migration", "bottleneck")):
            if len(challenges) < 2:
                challenges.append(point_entry)
        elif any(k in lower for k in ("role", "responsib", "engineer", "build", "design", "team")):
            if len(role_context) < 2:
                role_context.append(point_entry)
        else:
            if len(priorities) < 2:
                priorities.append(point_entry)

    if not priorities and not challenges and not role_context and cleaned_sources:
        first_s = cleaned_sources[0]
        sent = first_s["snippet"].split(".")[0].strip()
        priorities.append({
            "point": (sent[:80] + ".").replace("—", "-").replace("–", "-"),
            "source": first_s["id"],
        })

    sources_out = [
        {"id": s["id"], "title": s["title"], "domain": s["domain"], "url": s["url"]}
        for s in cleaned_sources[:4]
    ]

    return {
        "status": "ready",
        "schema_version": SCHEMA_VERSION,
        "is_sources_only": True,
        "fallback_label": "Sources found, summary unavailable",
        "summary": "Sources found, summary unavailable.",
        "priorities": priorities,
        "role_context": role_context,
        "challenges": challenges,
        "talking_points": [],
        "sources": sources_out,
        "confidence": "low",
        "reason": reason,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": company,
        "role": role,
        "cached": False,
        "strategic_insights": [f"{s['title']}: {s.get('snippet', '')[:100]}" for s in cleaned_sources[:3]],
        "technical_pain_points": [p["point"] for p in challenges] or [p["point"] for p in priorities],
        "recent_news": [],
    }


def build_job_posting_fallback(
    description: str,
    company: str,
    role: str,
    canonical_url: str = "",
) -> Optional[Dict[str, Any]]:
    """Build a grounded brief from the opportunity's own job posting text when web search fails."""
    clean_desc = re.sub(r"<[^>]+>", " ", description or "").strip()
    if len(clean_desc) < 40:
        return None

    # Extract sentences
    sentences = re.split(r"(?<=[.!?])\s+", clean_desc)
    role_points: List[str] = []
    priorities: List[str] = []

    for sent in sentences:
        s = sent.strip()
        if len(s.split()) < 4 or len(s.split()) > 25:
            continue
        low = s.lower()
        clean_s = (" ".join(s.split()[:22])).rstrip(".,;:") + "."
        clean_s = clean_s.replace("—", "-").replace("–", "-")

        if any(k in low for k in ("responsible", "will", "build", "lead", "manage", "collaborate")):
            if len(role_points) < 3 and clean_s not in role_points:
                role_points.append(clean_s)
        elif any(k in low for k in ("mission", "goal", "deliver", "experience", "protect", "scale")):
            if len(priorities) < 3 and clean_s not in priorities:
                priorities.append(clean_s)

    if not role_points and not priorities and sentences:
        s0 = " ".join(sentences[0].split()[:22]).rstrip(".,;:") + "."
        priorities.append(s0.replace("—", "-").replace("–", "-"))

    domain = "job posting"
    if canonical_url:
        domain = urlparse(canonical_url).netloc or "job posting"

    sources_out = [
        {
            "id": 1,
            "title": f"{role} Job Posting",
            "domain": domain,
            "url": canonical_url or "",
        }
    ]

    return {
        "status": "ready",
        "schema_version": SCHEMA_VERSION,
        "from_job_posting": True,
        "fallback_label": "From the job posting",
        "summary": f"From the {company} job posting for {role}.",
        "priorities": [{"point": p, "source": 1} for p in priorities],
        "role_context": [{"point": p, "source": 1} for p in role_points],
        "challenges": [],
        "talking_points": [],
        "sources": sources_out,
        "confidence": "low",
        "reason": "from_job_posting",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": company,
        "role": role,
        "cached": False,
        "strategic_insights": priorities[:2],
        "technical_pain_points": role_points[:2],
        "recent_news": [],
    }


def _base_empty_brief(
    company: str,
    role: str,
    status: str,
    msg_key: str,
    msg_val: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    b = {
        "status": status,
        "schema_version": SCHEMA_VERSION,
        "reason": reason or ("no_sources" if status == "empty" else "service_unavailable"),
        "summary": "",
        "priorities": [],
        "role_context": [],
        "challenges": [],
        "talking_points": [],
        "sources": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "confidence": "low",
        "message": msg_val,
        "company": company,
        "role": role,
        "strategic_insights": [],
        "technical_pain_points": [],
        "recent_news": [],
        "cached": False,
    }
    if msg_key:
        b[msg_key] = msg_val
    return b


def _build_empty_intel(
    company: str,
    role: str,
    message: str = "We could not find enough reliable information about this company.",
    reason: str = "no_sources",
) -> Dict[str, Any]:
    return _base_empty_brief(company, role, "empty", "", message, reason=reason)


def _build_error_intel(
    company: str,
    role: str,
    error: str = "We couldn't generate company intel right now. Please try again.",
    reason: str = "model_failed",
) -> Dict[str, Any]:
    return _base_empty_brief(company, role, "error", "error", error, reason=reason)


def _normalize_source_id(source_val: Any, valid_ids: Set[int]) -> Optional[int]:
    """Robustly normalize source IDs (int, string, bracketed, zero-based, list)."""
    if source_val is None:
        return None
    if isinstance(source_val, int):
        return source_val if source_val in valid_ids else (1 if source_val == 0 and 1 in valid_ids else None)
    if isinstance(source_val, str):
        for n in [int(x) for x in re.findall(r"\d+", source_val)]:
            if n in valid_ids:
                return n
            if n == 0 and 1 in valid_ids:
                return 1
    if isinstance(source_val, list) and source_val:
        return _normalize_source_id(source_val[0], valid_ids)
    return None


def _parse_json_safely(raw_text: str) -> Optional[Dict[str, Any]]:
    """Safely parse JSON from LLM output handling markdown fences and extraneous text."""
    if not raw_text or not raw_text.strip():
        return None
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw_text.strip(), flags=re.IGNORECASE)
    cand = raw_text[raw_text.find("{") : raw_text.rfind("}") + 1] if "{" in raw_text and "}" in raw_text else ""
    for candidate in (cleaned, cand):
        if candidate:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return None


STOPWORDS: Set[str] = {
    "the", "and", "that", "this", "with", "from", "have", "been", "will",
    "they", "their", "them", "what", "which", "about", "role", "team",
    "company", "focus", "work", "also", "into", "over", "more", "most",
    "such", "some", "other", "than", "then", "when", "where", "while",
    "for", "are", "can", "could", "should", "would", "its", "has", "had",
    "you", "your", "our", "were", "who", "whom", "whose"
}


def is_point_grounded(
    point_text: str,
    cited_source: Dict[str, Any],
    all_sources: List[Dict[str, Any]],
) -> bool:
    """Verifies that a summarized point is factually grounded in the provided sources.

    Checks:
    1. Numbers, percentages, and metrics must appear in the source texts.
    2. Key content words must have lexical support in the cited source or all sources.
    """
    if not point_text:
        return False

    all_sources_text = " ".join((s.get("snippet", "") + " " + s.get("title", "")) for s in all_sources).lower()

    # 1. Number / Metric grounding check
    point_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", point_text))
    point_numbers = {n for n in point_numbers if n not in ("1", "2", "3", "4", "5", "6")}
    source_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", all_sources_text))
    if point_numbers and not point_numbers.issubset(source_numbers):
        return False

    # 2. Content tokens grounding check
    tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", point_text) if w.lower() not in STOPWORDS]
    if not tokens:
        return True

    cited_text = (cited_source.get("snippet", "") + " " + cited_source.get("title", "")).lower()
    cited_matches = sum(1 for tok in tokens if tok in cited_text)
    all_matches = sum(1 for tok in tokens if tok in all_sources_text)

    if all_matches == 0:
        return False
    if len(tokens) >= 3 and cited_matches == 0 and all_matches < 2:
        return False

    return True


async def run_intel_refresh_job(job_id: str, opp_id: int, user_id: Optional[str] = None) -> None:
    """Execute background intelligence refresh and record final status."""
    from backend.memory.radar import get_opportunity_by_id
    from backend.services import winning_features

    await update_job(job_id, status="running")
    try:
        opp = await get_opportunity_by_id(opp_id, user_id=user_id)
        if not opp:
            await update_job(
                job_id,
                status="failed",
                reason="no_sources",
                error="Opportunity not found",
            )
            return

        brief = await winning_features.generate_company_intel_brief(opp, force_refresh=True)
        if brief.get("status") == "error":
            await update_job(
                job_id,
                status="failed",
                reason=brief.get("reason", "model_failed"),
                error=brief.get("error", "Failed to generate company intel"),
                result=brief,
            )
        else:
            await update_job(job_id, status="done", result=brief)
    except Exception as exc:
        logger.error("Intel job %s failed unexpectedly: %s", job_id, exc, exc_info=True)
        await update_job(
            job_id,
            status="failed",
            reason="model_failed",
            error=str(exc) or "Unexpected error generating company intelligence",
        )

