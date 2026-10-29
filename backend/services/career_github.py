"""
Compass — Career Copilot GitHub Profile Intelligence Service.

Extracts verifiable engineering evidence from public GitHub profiles and repositories
using the official GitHub REST API with bounded retrieval, rate-limit resilience,
strict prompt-injection defense, and transparent evidence classification.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import httpx

from backend.models_career import GitHubProfileIntelligence, GitHubRepoEvidence

logger = logging.getLogger("compass.services.career_github")

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_SEC = 8.0
MAX_REPOS_TO_ANALYZE = 8  # owned, non-fork repositories that get per-repo API calls
MAX_FORKS_LISTED = 5  # forks are listed without per-repo calls
REPO_LIST_PAGE_SIZE = 100
MAX_API_CALLS_PER_ANALYSIS = 25
MIN_LANGUAGE_SHARE = 0.05
MAX_USERNAME_LEN = 39
MAX_README_LENGTH = 2500

# "Languages" GitHub reports that are markup/config/build glue, not skills.
IGNORED_LANGUAGES = frozenset(
    name.lower()
    for name in (
        "HTML", "CSS", "SCSS", "Sass", "Less", "Shell", "Dockerfile", "Makefile", "CMake",
        "Jupyter Notebook", "Batchfile", "PowerShell", "TeX", "Vim script", "Roff", "Nix",
        "Procfile", "Smarty", "EJS", "Handlebars", "Mustache", "XSLT", "Gherkin", "Markdown",
        "Starlark", "M4", "Inno Setup",
    )
)
RESERVED_GITHUB_PATHS = frozenset(
    {"orgs", "settings", "marketplace", "topics", "explore", "features", "pricing", "login",
     "join", "about", "sponsors", "notifications", "issues", "pulls", "search", "collections",
     "organizations", "enterprise", "apps", "trending", "readme"}
)
TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__"})
CI_ROOT_FILES = frozenset({".gitlab-ci.yml", "jenkinsfile", ".travis.yml", "azure-pipelines.yml"})

# Strict prompt-injection and control-token sanitization patterns
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"assistant\s*:", re.IGNORECASE),
    re.compile(r"new\s+instruction\s*:", re.IGNORECASE),
    re.compile(r"<!--[\s\S]*?-->"),  # hidden markdown comments
]


def sanitize_external_text(text: Optional[str], max_len: int = MAX_README_LENGTH) -> str:
    """
    Sanitizes untrusted repository text (READMEs, commit messages) to neutralize prompt injection.
    Never allows external markdown or comments to act as prompt instructions.
    """
    if not text:
        return ""
    clean = text
    for pat in PROMPT_INJECTION_PATTERNS:
        clean = pat.sub("[REDACTED_EXTERNAL_CONTENT]", clean)
    clean = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", clean)
    return clean[:max_len].strip()


def _valid_username(name: str) -> bool:
    return (
        0 < len(name) <= MAX_USERNAME_LEN
        and re.fullmatch(r"[A-Za-z0-9-]+", name) is not None
        and not name.startswith("-")
        and not name.endswith("-")
        and "--" not in name
    )


def parse_github_username(user_input: str) -> Tuple[Optional[str], Optional[str]]:
    """Normalise a handle / profile URL. Returns (username, None) or (None, error message)."""
    clean = (user_input or "").strip()
    if not clean:
        return None, "Enter a GitHub username or profile URL."
    candidate = clean.lstrip("@")
    if "/" in candidate or "." in candidate:
        url = candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
        except ValueError:
            return None, "That does not look like a GitHub profile URL."
        if host not in ("github.com", "www.github.com"):
            return None, "Only github.com profile URLs are supported."
        parts = [p for p in (parsed.path or "").split("/") if p]
        if not parts:
            return None, "The URL does not include a GitHub username."
        candidate = parts[0]
        if candidate.lower() in RESERVED_GITHUB_PATHS:
            return None, "That URL points to a GitHub page or organization, not a user profile."
    if not _valid_username(candidate):
        return None, (
            "Invalid GitHub username: use 1-39 letters, digits or single hyphens, "
            "not starting or ending with a hyphen."
        )
    return candidate, None


def extract_username_from_input(user_input: str) -> str:
    """Extracts clean username from URL or handle ("" when invalid)."""
    name, _err = parse_github_username(user_input)
    return name or ""


class _Budget:
    """Per-analysis API call budget and failure state."""

    def __init__(self, limit: int = MAX_API_CALLS_PER_ANALYSIS):
        self.limit = limit
        self.calls = 0
        self.rate_limited = False
        self.exhausted_warned = False
        self.remaining_header: Optional[int] = None

    def note_headers(self, resp: Any) -> None:
        raw = (getattr(resp, "headers", None) or {}).get("x-ratelimit-remaining")
        try:
            if raw is not None:
                self.remaining_header = int(raw)
        except (TypeError, ValueError):
            pass


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    budget: _Budget,
    warnings: List[str],
    what: str,
    params: Optional[Dict[str, Any]] = None,
    warn_missing: bool = True,
) -> Tuple[str, Any]:
    """GET one GitHub API URL. Returns ("ok"|"missing"|"failed", json). Failures add a warning."""
    if budget.rate_limited:
        return "failed", None
    if budget.calls >= budget.limit:
        if not budget.exhausted_warned:
            budget.exhausted_warned = True
            warnings.append(
                f"Stopped after {budget.limit} GitHub API calls to protect your rate limit; "
                "some repositories were not fully checked."
            )
        return "failed", None
    budget.calls += 1
    try:
        resp = await client.get(url, params=params) if params else await client.get(url)
    except Exception as exc:  # never include exc text: it may carry request headers
        logger.warning("GitHub request failed (%s): %s", what, type(exc).__name__)
        warnings.append(f"{what}: could not reach GitHub ({type(exc).__name__}).")
        return "failed", None
    budget.note_headers(resp)
    code = resp.status_code
    if code == 200:
        try:
            return "ok", resp.json()
        except ValueError:
            warnings.append(f"{what}: GitHub returned an unreadable response.")
            return "failed", None
    if code == 404:
        if warn_missing:
            warnings.append(f"{what}: not found (HTTP 404).")
        return "missing", None
    if code in (403, 429):
        budget.rate_limited = True
        warnings.append(
            f"{what}: GitHub API rate limit exceeded or access forbidden (HTTP {code}). "
            "Add an optional personal access token or try again later; remaining checks were skipped."
        )
        return "failed", None
    warnings.append(f"{what}: GitHub API returned error status {code}.")
    return "failed", None


def _failed_result(username: str, warnings: List[str], total: int = 0) -> GitHubProfileIntelligence:
    return GitHubProfileIntelligence(
        username=username or "unknown",
        profile_url=f"https://github.com/{username}" if username else "https://github.com",
        total_public_repos=total,
        warnings=warnings,
        evidence_summary="No repositories could be analyzed.",
        status="failed",
    )


def _is_test_file(name: str) -> bool:
    return name.startswith("test_") or name.endswith(
        ("_test.go", "_test.py", ".test.js", ".test.ts", ".test.jsx", ".test.tsx",
         ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx")
    )


def _kind(item: Dict[str, Any]) -> str:
    return str(item.get("type") or "")


async def _detect_tests(client, base, names, budget, warnings, repo_name) -> Optional[bool]:
    if any(_is_test_file(n) for n, i in names.items() if _kind(i) != "dir"):
        return True
    unknown = False
    for tdir in [n for n, i in names.items() if n in TEST_DIR_NAMES and _kind(i) != "file"]:
        status, data = await _fetch(
            client, f"{base}/contents/{quote(tdir)}", budget, warnings,
            f"{repo_name} tests directory", warn_missing=False,
        )
        if status == "ok" and isinstance(data, list) and data:
            return True
        unknown = unknown or status == "failed"
    return None if unknown else False


def _has_workflow_file(data: Any) -> bool:
    return isinstance(data, list) and any(
        isinstance(f, dict) and f.get("type", "file") == "file"
        and str(f.get("name", "")).lower().endswith((".yml", ".yaml"))
        for f in data
    )


async def _detect_ci(client, base, names, budget, warnings, repo_name) -> Optional[bool]:
    if any(n in CI_ROOT_FILES and _kind(i) != "dir" for n, i in names.items()):
        return True
    unknown = False
    if ".github" in names:
        status, data = await _fetch(
            client, f"{base}/contents/.github/workflows", budget, warnings,
            f"{repo_name} workflows", warn_missing=False,
        )
        if status == "ok" and _has_workflow_file(data):
            return True
        unknown = unknown or status == "failed"
    if ".circleci" in names:
        status, data = await _fetch(
            client, f"{base}/contents/.circleci", budget, warnings,
            f"{repo_name} CircleCI config", warn_missing=False,
        )
        if status == "ok" and isinstance(data, list) and any(
            isinstance(f, dict) and str(f.get("name", "")).lower() == "config.yml" for f in data
        ):
            return True
        unknown = unknown or status == "failed"
    return None if unknown else False


def _skills_from_bytes(byte_totals: Dict[str, int]) -> List[str]:
    total = sum(byte_totals.values())
    if total <= 0:
        return []
    return sorted(
        lang for lang, n in byte_totals.items()
        if lang.lower() not in IGNORED_LANGUAGES and n / total >= MIN_LANGUAGE_SHARE
    )


def _repo_info(r: Dict[str, Any], username: str) -> Dict[str, Any]:
    name = r.get("name", "")
    owner_login = (r.get("owner") or {}).get("login", username)
    is_fork = bool(r.get("fork", False))
    return {
        "name": name,
        "owner": owner_login,
        "is_fork": is_fork,
        "is_owned": owner_login.lower() == username.lower() and not is_fork,
        "url": r.get("html_url", f"https://github.com/{owner_login}/{name}"),
        "desc": sanitize_external_text(r.get("description") or "", 200),
        "lang": r.get("language"),
    }


def _fork_evidence(info: Dict[str, Any]) -> GitHubRepoEvidence:
    return GitHubRepoEvidence(
        repo_name=info["name"], repo_url=info["url"], owner=info["owner"], is_fork=True,
        is_owned=False, description=info["desc"] or f"Repository {info['name']}",
        primary_language=info["lang"], detected_technologies=[], has_tests=None, has_ci_cd=None,
        analysis_timestamp=datetime.now(timezone.utc),
        limitations=["Fork - not your original work; tests, CI and languages were not inspected."],
        implementation_evidence=[],
    )


def _owned_evidence(
    info: Dict[str, Any],
    lang_bytes: Optional[Dict[str, int]],
    has_tests: Optional[bool],
    has_ci: Optional[bool],
    has_docs: bool,
) -> GitHubRepoEvidence:
    techs = [info["lang"]] if info["lang"] and info["lang"].lower() not in IGNORED_LANGUAGES else []
    ranked = sorted(lang_bytes or {}, key=lambda k: -(lang_bytes or {})[k])
    for lang in ranked:
        if lang not in techs and lang.lower() not in IGNORED_LANGUAGES and len(techs) < 6:
            techs.append(lang)
    evidence: List[str] = []
    if has_tests:
        evidence.append("Automated test files or a non-empty test directory found.")
    if has_ci:
        evidence.append("CI configuration found (e.g. a GitHub Actions workflow file).")
    if info["lang"]:
        evidence.append(f"Core codebase authored in {info['lang']}.")
    limitations: List[str] = []
    if has_tests is None or has_ci is None:
        limitations.append("Test/CI status could not be determined (GitHub check incomplete).")
    if has_tests is False:
        limitations.append("No explicit automated test suite detected in root directory.")
    return GitHubRepoEvidence(
        repo_name=info["name"], repo_url=info["url"], owner=info["owner"], is_fork=False,
        is_owned=True, description=info["desc"] or f"Repository {info['name']}",
        primary_language=info["lang"], detected_technologies=techs, has_tests=has_tests,
        has_ci_cd=has_ci, has_documentation=has_docs,
        analysis_timestamp=datetime.now(timezone.utc),
        limitations=limitations, implementation_evidence=evidence,
    )


async def _collect_base_signals(client, owned, budget, warnings):
    """Pass 1: languages + root listing for each owned repo (the core signal comes first)."""
    langs: Dict[str, Optional[Dict[str, int]]] = {}
    roots: Dict[str, Optional[List[Any]]] = {}
    for info in owned:
        name = info["name"]
        base = f"{GITHUB_API_BASE}/repos/{quote(info['owner'])}/{quote(name)}"
        info["base"] = base
        st, data = await _fetch(client, f"{base}/languages", budget, warnings, f"{name} languages")
        langs[name] = (
            {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
            if st == "ok" and isinstance(data, dict) else None
        )
        st, data = await _fetch(client, f"{base}/contents", budget, warnings, f"{name} contents")
        roots[name] = data if st == "ok" and isinstance(data, list) else None
    return langs, roots


async def analyze_github_profile(
    username_or_url: str,
    token: Optional[str] = None,
    excluded_repos: Optional[List[str]] = None,
) -> GitHubProfileIntelligence:
    """
    Analyzes public repositories for a GitHub candidate.

    - Up to MAX_REPOS_TO_ANALYZE owned, non-fork repos get per-repo calls (forks are listed only)
    - Skills come only from owned repos, above a byte-share threshold, minus non-skill languages
    - Every failed sub-call adds a warning; unknown test/CI results are None, not False
    - Token is sent only to api.github.com as a Bearer header and is never logged or returned
    """
    username, parse_error = parse_github_username(username_or_url)
    if username is None:
        return _failed_result("", [parse_error or "Invalid GitHub username."])

    excluded_set: Set[str] = {r.lower() for r in (excluded_repos or [])}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Compass-Career-Copilot/1.0",
    }
    clean_token = (token or "").strip()
    if clean_token:
        headers["Authorization"] = f"Bearer {clean_token}"

    warnings: List[str] = []
    budget = _Budget()
    api_user = f"{GITHUB_API_BASE}/users/{quote(username)}"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC, headers=headers) as client:
        status, user_data = await _fetch(
            client, api_user, budget, warnings, f"GitHub user '{username}'", warn_missing=False
        )
        if status == "missing":
            return _failed_result(username, [f"GitHub user '{username}' was not found."])
        if status != "ok" or not isinstance(user_data, dict):
            return _failed_result(username, warnings or ["Unable to read the GitHub profile."])
        if str(user_data.get("type", "User")).lower() == "organization":
            return _failed_result(
                username, [f"'{username}' is a GitHub organization. Enter a personal account instead."]
            )
        total_public = int(user_data.get("public_repos", 0) or 0)

        low = budget.remaining_header is not None and budget.remaining_header < MAX_API_CALLS_PER_ANALYSIS
        if not clean_token and low:
            warnings.append(
                f"No GitHub token provided and only {budget.remaining_header} unauthenticated requests "
                "remain this hour; results may be incomplete."
            )

        status, raw_repos = await _fetch(
            client, f"{api_user}/repos", budget, warnings, "Repository list",
            params={"sort": "updated", "per_page": REPO_LIST_PAGE_SIZE, "type": "owner"},
        )
        if status != "ok" or not isinstance(raw_repos, list):
            return _failed_result(username, warnings or ["Could not list repositories."], total_public)

        infos = [_repo_info(r, username) for r in raw_repos if isinstance(r, dict) and r.get("name")]
        infos = [i for i in infos if i["name"].lower() not in excluded_set]
        owned = [i for i in infos if i["is_owned"]][:MAX_REPOS_TO_ANALYZE]
        forks = [i for i in infos if i["is_fork"]][:MAX_FORKS_LISTED]
        if not owned:
            warnings.append("No original (non-fork) public repositories were found to analyze.")

        langs, roots = await _collect_base_signals(client, owned, budget, warnings)

        analyzed_repos: List[GitHubRepoEvidence] = []
        byte_totals: Dict[str, int] = {}
        for info in owned:
            name = info["name"]
            for lang, n in (langs[name] or {}).items():
                byte_totals[lang] = byte_totals.get(lang, 0) + n
            has_tests: Optional[bool] = None
            has_ci: Optional[bool] = None
            has_docs = False
            root = roots[name]
            if root is not None:
                names = {str(i.get("name", "")).lower(): i for i in root if isinstance(i, dict)}
                has_docs = any(n.startswith("readme") or n in ("docs", "documentation") for n in names)
                has_tests = await _detect_tests(client, info["base"], names, budget, warnings, name)
                has_ci = await _detect_ci(client, info["base"], names, budget, warnings, name)
            analyzed_repos.append(_owned_evidence(info, langs[name], has_tests, has_ci, has_docs))

        analyzed_repos.extend(_fork_evidence(i) for i in forks)

    skills_list = _skills_from_bytes(byte_totals)
    if not byte_totals and owned:
        skills_list = sorted(
            {i["lang"] for i in owned if i["lang"] and i["lang"].lower() not in IGNORED_LANGUAGES}
        )
        if skills_list:
            warnings.append(
                "Language byte counts were unavailable; skills come from each repo's primary language only."
            )

    if not clean_token and budget.calls >= budget.limit - 5:
        warnings.append(
            "No GitHub token provided: unauthenticated requests are limited to 60 per hour and this "
            f"analysis used {budget.calls}."
        )

    summary = (
        f"Analyzed {len(owned)} original repositories for @{username} and listed {len(forks)} forks "
        "(forks are not analyzed). Technologies detected in your own repositories: "
        f"{', '.join(skills_list[:6]) if skills_list else 'None detected'}."
    )
    if not owned:
        state = "failed" if not forks else "partial"
    else:
        state = "partial" if warnings else "ok"
    return GitHubProfileIntelligence(
        username=username,
        profile_url=f"https://github.com/{username}",
        total_public_repos=total_public,
        analyzed_repos=analyzed_repos,
        detected_skills=skills_list,
        evidence_summary=summary,
        warnings=warnings,
        status=state,
    )
