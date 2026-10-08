"""
Compass — Tavily Domain Authority and Source Quality Classifier.

Distinguishes official documentation, academic/government sources, reputable technical
publications, and general web pages to prevent unverified sources from overwhelming
verified primary evidence.
"""

from __future__ import annotations

import enum
import re
import urllib.parse
from typing import Any, Dict, List, Optional


class AuthorityTier(str, enum.Enum):
    TIER_1_OFFICIAL = "tier_1_official"
    TIER_2_TECHNICAL = "tier_2_technical"
    TIER_3_GENERAL = "tier_3_general"


_TIER_1_DOMAINS = {
    # Official First-Party / Organizer Platforms
    "nebius.com",
    "docs.nebius.com",
    "nvidia.com",
    "developer.nvidia.com",
    "arxiv.org",
}

_TIER_2_DOMAINS = {
    # Platform & User-Generated Content Hosts (max Tier 2 per specification)
    "devpost.com",
    "github.com",
    "github.io",
    "raw.githubusercontent.com",
    "gitlab.com",
    "huggingface.co",
    "pypi.org",
    "npmjs.com",
    "crates.io",
    "pkg.go.dev",
    "notion.site",
    "medium.com",
    "substack.com",
    "stackoverflow.com",
    "stackexchange.com",
    "wikipedia.org",
    "nature.com",
    "ieee.org",
    "acm.org",
    "theverge.com",
    "techcrunch.com",
    "venturebeat.com",
    "towardsdatascience.com",
}

_OFFICIAL_PREFIXES = ("docs.", "api.", "developer.", "dev.", "help.", "support.", "learn.")


def extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        domain = (parsed.hostname or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def classify_domain_authority(
    url: str,
    organizer_domains: Optional[set[str]] = None,
    target_entity: Optional[str] = None,
    is_entity_bound: bool = False,
    page_title_matches_entity: bool = False,
    pinned_event_prefixes: Optional[List[str]] = None,
    trusted_event_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify the source authority of a URL.

    Rules:
      - Tier 1: User-pinned trusted event URL, Government/academic domains, pinned organizer domains from config, or platform event pages meeting the Event-Page Rule.
      - Event-Page Rule: Platform-hosted pages (Devpost, Lablab, etc.) count as official (Tier 1) for that event ONLY when
        the page title/organizer matches target_entity AND the URL is pinned or entity-bound; otherwise Tier 2.
      - Tier 2: General platform and user-generated content hosts (github, medium, unpinned devpost, etc.).
      - Tier 3: General web pages.
    """
    domain = extract_domain(url)
    if not domain:
        return {
            "tier": AuthorityTier.TIER_3_GENERAL.value,
            "badge": "General Web",
            "weight": 0.50,
            "domain": "unknown",
            "reason": "Missing or unparseable URL",
        }

    # Check user-pinned trusted event URL (per-user / per-task input)
    if trusted_event_url:
        t_clean = trusted_event_url.strip().lower()
        u_clean = url.strip().lower()
        if u_clean == t_clean or u_clean.startswith(t_clean.rstrip("/") + "/") or (t_clean in u_clean and len(t_clean) > 8):
            return {
                "tier": AuthorityTier.TIER_1_OFFICIAL.value,
                "badge": "User-trusted source",
                "weight": 1.0,
                "domain": domain,
                "reason": f"Matched per-user trusted event URL ({trusted_event_url})",
            }

    # Check Gov / Edu top-level domains
    if domain.endswith(".gov") or domain.endswith(".gov.uk") or domain.endswith(".gov.in"):
        return {
            "tier": AuthorityTier.TIER_1_OFFICIAL.value,
            "badge": "Official Gov",
            "weight": 1.0,
            "domain": domain,
            "reason": "Government domain",
        }
    if domain.endswith(".edu") or domain.endswith(".ac.uk"):
        return {
            "tier": AuthorityTier.TIER_1_OFFICIAL.value,
            "badge": "Academic (.edu)",
            "weight": 0.95,
            "domain": domain,
            "reason": "Accredited academic institution",
        }

    from backend.config import get_settings
    settings = get_settings()
    configured_tier_1 = set(getattr(settings, "PINNED_TIER_1_DOMAINS", []))
    if organizer_domains:
        configured_tier_1.update(od.strip().lower() for od in organizer_domains if od)

    # Check explicitly pinned organizer domains from config
    for od in configured_tier_1:
        if domain == od or domain.endswith("." + od):
            return {
                "tier": AuthorityTier.TIER_1_OFFICIAL.value,
                "badge": "Official Organizer",
                "weight": 1.0,
                "domain": domain,
                "reason": f"Matched pinned organizer domain ({od})",
            }

    # Absolute blacklist: Devpost project submissions (/software/...), GitHub, Medium, etc. NEVER promoted to Tier 1
    parsed_url = urllib.parse.urlsplit(url.strip())
    path_lower = (parsed_url.path or "").lower()
    is_user_submission_path = "/software/" in path_lower or "/project/" in path_lower
    is_user_content_host = any(
        domain == d or domain.endswith("." + d)
        for d in ("github.com", "medium.com", "substack.com", "reddit.com", "twitter.com", "x.com")
    )

    if is_user_content_host:
        return {
            "tier": AuthorityTier.TIER_2_TECHNICAL.value,
            "badge": "Community / Code Host",
            "weight": 0.70,
            "domain": domain,
            "reason": f"User-generated content host ({domain}) is restricted to Tier 2",
        }

    # Event-Page Rule for Platform-Hosted Pages
    platform_hosts = {"devpost.com", "lablab.ai", "dorahacks.io", "kaggle.com"}
    is_platform = any(domain == p or domain.endswith("." + p) for p in platform_hosts)
    if is_platform:
        # Devpost project pages are user-submitted software entries — NEVER promoted to Tier 1
        if is_user_submission_path:
            return {
                "tier": AuthorityTier.TIER_2_TECHNICAL.value,
                "badge": "Platform / User Submission",
                "weight": 0.70,
                "domain": domain,
                "reason": "Platform user-submitted project page (/software/...) cannot be Tier 1 official",
            }

        # Strict Event-Page Rule: Official status for platform hosts requires exact match
        # against a pinned list (host + path prefix) from config or user input.
        # Substring/subdomain matching is completely removed.
        configured_prefixes = set(getattr(settings, "PINNED_EVENT_PREFIXES", []))
        if pinned_event_prefixes:
            configured_prefixes.update(p.strip().lower() for p in pinned_event_prefixes if p)

        url_clean = url.strip().lower()
        # Normalizes both https://host/path and host/path
        matches_pinned_prefix = False
        for pref in configured_prefixes:
            p_clean = pref.strip().lower()
            if not p_clean.startswith("http://") and not p_clean.startswith("https://"):
                # Host/prefix match against parsed URL without scheme
                no_scheme_url = parsed_url.netloc.lower() + (parsed_url.path or "").lower()
                if no_scheme_url.startswith(p_clean.rstrip("/")):
                    matches_pinned_prefix = True
                    break
            else:
                if url_clean.startswith(p_clean.rstrip("/") + "/") or url_clean == p_clean.rstrip("/"):
                    matches_pinned_prefix = True
                    break

        matches_entity_binding = False
        if is_entity_bound:
            if target_entity:
                te = target_entity.strip().lower()
                sub = domain.split(".")[0] if "." in domain else domain
                if sub.startswith(te + "-") or sub.startswith(te + ".") or sub == te or te in sub:
                    matches_entity_binding = True
            elif page_title_matches_entity:
                matches_entity_binding = True

        if matches_pinned_prefix or matches_entity_binding:
            badge_suffix = "(Pinned Platform)" if matches_pinned_prefix else "(Entity Bound)"
            return {
                "tier": AuthorityTier.TIER_1_OFFICIAL.value,
                "badge": f"Official Event Page {badge_suffix}",
                "weight": 0.95,
                "domain": domain,
                "reason": f"Platform-hosted event matches official criteria ({domain})",
            }
        else:
            return {
                "tier": AuthorityTier.TIER_2_TECHNICAL.value,
                "badge": "Platform / Community Host",
                "weight": 0.75,
                "domain": domain,
                "reason": f"Platform host ({domain}) without exact match in pinned event list stays Tier 2",
            }

    # Check Tier 1 primary official domains
    for t1 in _TIER_1_DOMAINS:
        if domain == t1 or domain.endswith("." + t1):
            return {
                "tier": AuthorityTier.TIER_1_OFFICIAL.value,
                "badge": "Official Organizer",
                "weight": 1.0,
                "domain": domain,
                "reason": f"Recognized primary authority ({t1})",
            }

    # Check Tier 2 platform & community hosts (max Tier 2)
    for t2 in _TIER_2_DOMAINS:
        if domain == t2 or domain.endswith("." + t2):
            return {
                "tier": AuthorityTier.TIER_2_TECHNICAL.value,
                "badge": "Platform / Community Host",
                "weight": 0.75,
                "domain": domain,
                "reason": f"Platform or community host ({t2})",
            }

    # Default to Tier 3 general web
    return {
        "tier": AuthorityTier.TIER_3_GENERAL.value,
        "badge": "General Web",
        "weight": 0.50,
        "domain": domain,
        "reason": "General public web source",
    }


def compute_composite_score(tavily_score: float, authority_weight: float) -> float:
    """Calculate blended relevance + authority ranking score.

    Weighted 60% Tavily semantic relevance + 40% source domain authority.
    """
    safe_tavily = max(0.0, min(1.0, float(tavily_score or 0.5)))
    safe_auth = max(0.0, min(1.0, float(authority_weight or 0.5)))
    return round((safe_tavily * 0.60) + (safe_auth * 0.40), 4)


def sort_and_enrich_sources(results: List[Dict[str, Any]], trusted_event_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Enrich each search result with domain authority tier, badge, and composite score.

    Sorts highest composite score first.
    """
    enriched = []
    for r in results:
        url = r.get("url") or ""
        auth_meta = classify_domain_authority(url, trusted_event_url=trusted_event_url)
        tavily_score = float(r.get("score") or 0.5)
        composite = compute_composite_score(tavily_score, auth_meta["weight"])

        item = dict(r)
        item["authority_tier"] = auth_meta["tier"]
        item["authority_badge"] = auth_meta["badge"]
        item["authority_weight"] = auth_meta["weight"]
        item["domain"] = auth_meta["domain"]
        item["composite_score"] = composite
        enriched.append(item)

    # Sort descending by composite score, then by raw score
    enriched.sort(key=lambda x: (x.get("composite_score", 0.0), x.get("score", 0.0)), reverse=True)
    return enriched
