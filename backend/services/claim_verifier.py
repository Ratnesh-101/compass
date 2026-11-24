"""
Compass — Resume Factual Claim Verifier Service.

Extracts verifiable public entities (institutions, employers, certifications,
awards, publications, project/profile links) from resumes, cross-references
against real-world web data via Tavily with SSRF-safe reachability checks,
and evaluates evidence strictly and safely without assuming or claiming fraud.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from backend.models_career import ResumeContent, safe_http_url
from backend.services.budgets import BudgetExceededError
from backend.services.security import safe_http_get_with_url
from backend.services.tavily import (
    sanitize_untrusted_text,
    search as default_tavily_search,
    tavily_available,
)

logger = logging.getLogger("compass.services.claim_verifier")

PLACEHOLDER_VALUES = {
    "compass candidate",
    "n/a",
    "na",
    "tbd",
    "none",
    "unknown",
    "null",
    "undefined",
    "-",
}

LEGAL_SUFFIX_WORDS = {
    "inc",
    "ltd",
    "llp",
    "llc",
    "pvt",
    "private",
    "limited",
    "corp",
    "corporation",
    "technologies",
    "technology",
    "labs",
    "the",
}

PHRASE_PATTERNS = [
    re.compile(r"\b(university of|institute of)\b", re.IGNORECASE),
]


class ClaimEvidence(BaseModel):
    title: str
    url: str


class ClaimCheck(BaseModel):
    kind: str
    text: str
    status: Literal["found", "not_found", "cannot_check", "error"]
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    note: str


class ClaimVerificationReport(BaseModel):
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tavily_used: bool = False
    checks: list[ClaimCheck] = Field(default_factory=list)
    found: int = 0
    not_found: int = 0
    cannot_check: int = 0
    errors: int = 0
    summary: str = ""
    notice: str = ""


UNVERIFIABLE_LINK_DOMAINS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
)


def _is_unverifiable_link_host(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in UNVERIFIABLE_LINK_DOMAINS)
    except Exception:
        return False


def _cap_word_boundary(text: str, max_len: int = 120) -> str:
    if len(text) <= max_len:
        return text
    cutoff = text[:max_len]
    if text[max_len].isspace():
        return cutoff.strip()
    last_space = cutoff.rfind(" ")
    if last_space > 0:
        return cutoff[:last_space].strip()
    return cutoff.strip()


def _clean_claim_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    if s.count("(") > s.count(")"):
        s = s[: s.rfind("(")].strip()
    if s.count("[") > s.count("]"):
        s = s[: s.rfind("[")].strip()
    s = s.rstrip(" ,;:-.")
    if len(s) > 120:
        s = _cap_word_boundary(s, 120)
        if s.count("(") > s.count(")"):
            s = s[: s.rfind("(")].strip()
        if s.count("[") > s.count("]"):
            s = s[: s.rfind("[")].strip()
        s = s.rstrip(" ,;:-.")
    return s.strip()


def _is_placeholder(val: Optional[str]) -> bool:
    if not val or not isinstance(val, str):
        return True
    cleaned = val.strip().lower()
    return not cleaned or cleaned in PLACEHOLDER_VALUES


def extract_claims(content: ResumeContent) -> list[dict]:
    """Extract at most 12 verifiable claims in strict priority order:

    1. Education institutions
    2. Employers (experience and internships, with role title context)
    3. Certifications
    4. Awards and hackathons
    5. Publications
    6. Links (github/portfolio, linkedin, relevant_links, project links)
    """
    claims: list[dict] = []
    seen: set[str] = set()

    def add_claim(
        kind: str,
        text_val: str,
        entity_val: str,
        query_val: Optional[str] = None,
        context_val: Optional[str] = None,
        url_val: Optional[str] = None,
    ) -> bool:
        if len(claims) >= 12:
            return False
        clean_text = _clean_claim_text(text_val) if kind != "link" else text_val.strip()[:120]
        clean_entity = _clean_claim_text(entity_val) if kind != "link" else entity_val.strip().strip('"').strip("'")
        clean_entity = clean_entity.strip('"').strip("'")
        if _is_placeholder(clean_entity):
            return True
        dedup_key = clean_entity.lower()
        if dedup_key in seen:
            return True
        seen.add(dedup_key)

        claim_item: Dict[str, Any] = {
            "kind": kind,
            "text": clean_text,
            "entity": clean_entity,
            "query": query_val,
        }
        if context_val:
            claim_item["context"] = context_val
        if url_val:
            claim_item["url"] = url_val
        claims.append(claim_item)
        return len(claims) < 12

    # 1. Education institutions
    for edu in getattr(content, "education", []) or []:
        inst = getattr(edu, "institution", "") or ""
        cleaned_inst = _clean_claim_text(inst)
        if cleaned_inst and not add_claim(
            "education",
            cleaned_inst,
            cleaned_inst,
            f'"{cleaned_inst}" university OR college',
            getattr(edu, "degree", None),
        ):
            return claims[:12]

    # 2. Employers from experience and internships
    for exp in (getattr(content, "experience", []) or []) + (getattr(content, "internships", []) or []):
        comp = getattr(exp, "company", "") or ""
        role = getattr(exp, "role_title", "") or ""
        cleaned_comp = _clean_claim_text(comp)
        if cleaned_comp and not add_claim(
            "employer",
            cleaned_comp,
            cleaned_comp,
            f'"{cleaned_comp}" company',
            role.strip() if role else None,
        ):
            return claims[:12]

    # 3. Certifications
    for cert in getattr(content, "certifications", []) or []:
        cleaned_cert = _clean_claim_text(cert) if isinstance(cert, str) else ""
        if cleaned_cert and not add_claim("certification", cleaned_cert, cleaned_cert, f'"{cleaned_cert}" certification'):
            return claims[:12]

    # 4. Awards & Hackathons
    for award in (getattr(content, "awards", []) or []) + (getattr(content, "hackathons", []) or []):
        cleaned_award = _clean_claim_text(award) if isinstance(award, str) else ""
        if cleaned_award and not add_claim("award", cleaned_award, cleaned_award, f'"{cleaned_award}"'):
            return claims[:12]

    # 5. Publications
    for pub in getattr(content, "publications", []) or []:
        cleaned_pub = _clean_claim_text(pub) if isinstance(pub, str) else ""
        if cleaned_pub and not add_claim("publication", cleaned_pub, cleaned_pub, f'"{cleaned_pub}"'):
            return claims[:12]

    # 6. Links
    link_candidates: list[str] = []
    if getattr(content, "github_or_portfolio", None):
        link_candidates.append(content.github_or_portfolio)
    if getattr(content, "linkedin_url", None):
        link_candidates.append(content.linkedin_url)
    for rl in getattr(content, "relevant_links", []) or []:
        if rl:
            link_candidates.append(rl)
    for proj in getattr(content, "projects", []) or []:
        if getattr(proj, "project_url", None):
            link_candidates.append(proj.project_url)
        if getattr(proj, "repo_url", None):
            link_candidates.append(proj.repo_url)

    for raw_link in link_candidates:
        if not raw_link or _is_placeholder(raw_link):
            continue
        candidate = raw_link.strip()
        if not candidate.startswith(("http://", "https://")):
            if safe_http_url("https://" + candidate):
                candidate = "https://" + candidate
        valid_url = safe_http_url(candidate)
        if not valid_url:
            continue
        if not add_claim("link", valid_url, valid_url, None, None, valid_url):
            return claims[:12]

    return claims[:12]


def has_self_reported_content(content: ResumeContent) -> bool:
    """Check if resume contains self-reported work, achievements or skills."""
    if getattr(content, "skills", None) or getattr(content, "achievements", None) or getattr(content, "summary", None):
        return True
    for p in getattr(content, "projects", []) or []:
        if getattr(p, "description", None) or getattr(p, "highlights", None):
            return True
    for exp in (getattr(content, "experience", []) or []) + (getattr(content, "internships", []) or []):
        if getattr(exp, "highlights", None):
            return True
    return False


def extract_significant_tokens(entity: str) -> list[str]:
    """Normalize entity name and return significant tokens."""
    if not entity:
        return []
    cleaned = entity.lower()
    for pattern in PHRASE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    raw_tokens = [t for t in cleaned.split() if t]
    filtered = [t for t in raw_tokens if t not in LEGAL_SUFFIX_WORDS and len(t) > 1]
    return filtered if filtered else raw_tokens


def evaluate_search_result(
    entity: str,
    results: list[dict],
) -> tuple[str, list[ClaimEvidence], str]:
    """Pure, testable search result evaluation against an entity name."""
    sig_tokens = extract_significant_tokens(entity)
    if not sig_tokens:
        return ("cannot_check", [], "No entity name provided to evaluate.")

    num_tokens = len(sig_tokens)
    concat_candidates: list[str] = []
    if len(sig_tokens) == 1:
        if len(sig_tokens[0]) >= 4:
            concat_candidates.append(sig_tokens[0])
    elif len(sig_tokens) >= 2:
        all_concat = "".join(sig_tokens)
        if len(all_concat) >= 4:
            concat_candidates.append(all_concat)
        first_two = sig_tokens[0] + sig_tokens[1]
        if len(first_two) >= 4 and first_two not in concat_candidates:
            concat_candidates.append(first_two)

    matching_evidence: list[ClaimEvidence] = []

    for r in results:
        raw_url = r.get("url") or ""
        valid_url = safe_http_url(raw_url)
        if not valid_url:
            continue

        sanitized_title = sanitize_untrusted_text(r.get("title") or "").strip()[:140]
        parsed = urlparse(valid_url)
        url_text = f"{parsed.netloc} {parsed.path}".lower()

        score = float(r.get("score") or 0.0)
        snippet_text = sanitize_untrusted_text(r.get("content") or "").lower() if score >= 0.5 else ""
        title_text = sanitized_title.lower()

        netloc = parsed.netloc.lower().split(":", 1)[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        cleaned_host = netloc.replace(".", "").replace("-", "")

        host_matched = bool(concat_candidates and any(cand in cleaned_host for cand in concat_candidates))

        if host_matched:
            matches = num_tokens
        else:
            matches = 0
            for token in sig_tokens:
                token_pattern = r"\b" + re.escape(token) + r"\b"
                if (
                    re.search(token_pattern, title_text)
                    or re.search(token_pattern, url_text)
                    or (snippet_text and re.search(token_pattern, snippet_text))
                ):
                    matches += 1

        is_match = (matches == num_tokens) if num_tokens <= 2 else ((matches / num_tokens) >= 0.8)
        if is_match:
            title_to_store = sanitized_title if sanitized_title else valid_url[:140]
            matching_evidence.append(ClaimEvidence(title=title_to_store, url=valid_url))

    if matching_evidence:
        return ("found", matching_evidence[:3], "Public web reference found.")

    return (
        "not_found",
        [],
        "No public page matching this name was found. That does not mean it is false: it may be a small or new organisation, or spelled differently.",
    )


async def check_link_reachability(
    url: str,
    fetch: Optional[Any] = None,
) -> tuple[str, list[ClaimEvidence], str]:
    """Check link reachability using SSRF-safe fetcher or custom injected fetch."""
    valid_url = safe_http_url(url)
    if not valid_url:
        return ("cannot_check", [], "Invalid link URL.")

    if _is_unverifiable_link_host(valid_url):
        return (
            "cannot_check",
            [],
            "This site blocks automated checks, so it cannot confirm the page exists. Open the link yourself to confirm.",
        )

    if fetch is not None:
        try:
            res = await fetch(valid_url)
            status_code = res if isinstance(res, int) else (res[0] if isinstance(res, tuple) else getattr(res, "status_code", int(res)))
        except asyncio.TimeoutError:
            return ("error", [], "The link check timed out.")
        except Exception as exc:
            err_msg = str(exc).lower()
            return ("error", [], "The link check timed out." if ("timeout" in err_msg or "timed out" in err_msg) else "The check did not finish.")
    else:
        try:
            status_code, _b, _h, _u = await safe_http_get_with_url(
                valid_url,
                max_redirects=3,
                timeout=8.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompassClaimVerifier/1.0", "Accept": "*/*"},
            )
        except ValueError as blocked:
            return ("error", [], "Too many redirects.") if "redirect" in str(blocked).lower() else ("cannot_check", [], "Link cannot be safely checked online.")
        except asyncio.TimeoutError:
            return ("error", [], "The link check timed out.")
        except Exception as exc:
            err_str = str(exc).lower()
            return ("error", [], "The link check timed out." if ("timeout" in err_str or "timed out" in err_str) else "The check did not finish.")

    if 200 <= status_code <= 399:
        return ("found", [ClaimEvidence(title=valid_url[:140], url=valid_url)], "The link opens.")
    elif status_code in (404, 410):
        return ("not_found", [], "The link returned 'not found'.")
    elif status_code in (401, 403, 429, 999):
        return ("cannot_check", [], "This site blocks automated checks; open it yourself to confirm.")
    return ("error", [], f"The link returned HTTP {status_code}.")


def _format_summary(checks: list[ClaimCheck]) -> str:
    total = len(checks)
    if total == 0:
        return "No verifiable claims found in resume."
    found = sum(1 for c in checks if c.status == "found")
    not_found = sum(1 for c in checks if c.status == "not_found")
    cannot_check = sum(1 for c in checks if c.status == "cannot_check")
    errors = sum(1 for c in checks if c.status == "error")

    parts: list[str] = []
    if found:
        parts.append(f"{found} found online")
    if not_found:
        parts.append(f"{not_found} not found")
    if cannot_check:
        parts.append(f"{cannot_check} could not be checked")
    if errors:
        parts.append(f"{errors} error{'s' if errors > 1 else ''}")

    details = ", ".join(parts) if parts else "0 checked"
    noun = "claim" if total == 1 else "claims"
    return f"Checked {total} {noun}: {details}."


async def verify_claims(
    content: ResumeContent,
    *,
    search: Optional[Any] = None,
    fetch: Optional[Any] = None,
    max_claims: int = 12,
    concurrency: int = 4,
    budget_seconds: float = 40.0,
) -> ClaimVerificationReport:
    """Verify resume claims online with concurrency, time budget, and graceful fallback.

    Never raises an unhandled exception.
    """
    try:
        raw_claims = extract_claims(content)
        claims = raw_claims[:max_claims]

        tavily_search = search if search is not None else default_tavily_search
        tavily_ok = True if search is not None else tavily_available()
        tavily_used = tavily_ok
        notice = "" if tavily_ok else "Online checking (Tavily) is not available at the moment, so only link checks ran. Try again later."

        sem = asyncio.Semaphore(concurrency)
        start_time = time.monotonic()
        deadline = start_time + budget_seconds

        async def verify_single_claim(claim: dict) -> ClaimCheck:
            nonlocal tavily_used, notice
            kind = claim.get("kind", "unknown")
            text = claim.get("text", "")

            # 1. Link claims
            if kind == "link":
                url = claim.get("url") or claim.get("entity") or text
                async with sem:
                    rem = max(0.1, deadline - time.monotonic())
                    if rem <= 0.2:
                        return ClaimCheck(kind=kind, text=text, status="error", evidence=[], note="The check did not finish.")
                    try:
                        st, ev, nt = await asyncio.wait_for(check_link_reachability(url, fetch=fetch), timeout=min(rem, 8.5))
                        return ClaimCheck(kind=kind, text=text, status=st, evidence=ev, note=nt)
                    except Exception:
                        return ClaimCheck(kind=kind, text=text, status="error", evidence=[], note="The check did not finish.")

            # 2. Web search claims
            if not tavily_used:
                return ClaimCheck(kind=kind, text=text, status="cannot_check", evidence=[], note="Online verification is not available right now.")

            query = claim.get("query") or f'"{claim.get("entity", text)}"'
            entity = claim.get("entity", text)

            async with sem:
                rem = max(0.1, deadline - time.monotonic())
                if rem <= 0.2:
                    return ClaimCheck(kind=kind, text=text, status="error", evidence=[], note="The check did not finish.")
                try:
                    res = await asyncio.wait_for(
                        tavily_search(query=query, max_results=5, search_depth="basic"),
                        timeout=min(rem, 15.0),
                    )
                    results = res.get("results", []) if isinstance(res, dict) else []
                    st, ev, nt = evaluate_search_result(entity, results)
                    return ClaimCheck(kind=kind, text=text, status=st, evidence=ev, note=nt)
                except (RuntimeError, BudgetExceededError):
                    tavily_used = False
                    notice = "Online checking (Tavily) is not available at the moment, so only link checks ran. Try again later."
                    return ClaimCheck(kind=kind, text=text, status="cannot_check", evidence=[], note="Online verification is not available right now.")
                except Exception as exc:
                    status_code = getattr(exc, "status_code", None)
                    if status_code is None and hasattr(exc, "response"):
                        status_code = getattr(exc.response, "status_code", None)
                    if status_code in (402, 429):
                        tavily_used = False
                        notice = "Online checking (Tavily) is not available at the moment, so only link checks ran. Try again later."
                        return ClaimCheck(kind=kind, text=text, status="cannot_check", evidence=[], note="Online verification is not available right now.")
                    return ClaimCheck(kind=kind, text=text, status="error", evidence=[], note="The check did not finish.")

        tasks = [verify_single_claim(c) for c in claims]
        checks: list[ClaimCheck] = []
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, ClaimCheck):
                    checks.append(r)
                else:
                    checks.append(ClaimCheck(kind=claims[i].get("kind", "unknown"), text=claims[i].get("text", ""), status="error", evidence=[], note="The check did not finish."))

        if has_self_reported_content(content):
            checks.append(
                ClaimCheck(
                    kind="self_reported",
                    text="Self-reported achievements and project contributions",
                    status="cannot_check",
                    evidence=[],
                    note="Your own work and results cannot be checked on the web; keep wording you can back up.",
                )
            )

        return ClaimVerificationReport(
            checked_at=datetime.now(timezone.utc),
            tavily_used=tavily_used,
            checks=checks,
            found=sum(1 for c in checks if c.status == "found"),
            not_found=sum(1 for c in checks if c.status == "not_found"),
            cannot_check=sum(1 for c in checks if c.status == "cannot_check"),
            errors=sum(1 for c in checks if c.status == "error"),
            summary=_format_summary(checks),
            notice=notice,
        )
    except Exception as exc:
        logger.error(f"verify_claims caught unexpected exception: {exc}", exc_info=True)
        return ClaimVerificationReport(
            checked_at=datetime.now(timezone.utc),
            tavily_used=False,
            checks=[],
            found=0,
            not_found=0,
            cannot_check=0,
            errors=1,
            summary="Verification could not complete.",
            notice="An unexpected error occurred during verification.",
        )
