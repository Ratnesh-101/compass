"""Honesty tests for claim verification and GitHub rate-limit messages.

(A) Links on sites that block bots are "cannot_check" without a fetch; claim texts are tidy.
(B) A rate limit hit part-way through a GitHub analysis gives one friendly warning.

No network, no database. All HTTP goes through fakes.
"""
from __future__ import annotations

import re
import time
from types import SimpleNamespace

import httpx
import pytest

import backend.config
import backend.services.career_github as cg
from backend.models_career import ResumeContent, ResumeExperienceItem
from backend.services import claim_verifier as cv

REAL_ASYNC_CLIENT = httpx.AsyncClient
FAKE_TOKEN = "ghp_FAKE_HONESTY_TOKEN_000"
SECRET_REPO = "zebra-secret-project"


# ---------------------------------------------------------------- helpers (A)

def _content(**kw) -> ResumeContent:
    base = dict(full_name="Asha Verma", email="asha@example.com")
    base.update(kw)
    return ResumeContent(**base)


def _recording_fetch(code=200):
    calls: list[str] = []

    async def fetch(url, **kw):
        calls.append(url)
        return code

    return fetch, calls


async def _no_search(query, **kw):
    return {"results": []}


BLOCKED_URLS = [
    "https://linkedin.com/in/asha-verma",
    "https://www.linkedin.com/in/asha-verma",
    "https://in.linkedin.com/in/asha-verma",
    "https://facebook.com/asha.verma",
    "https://www.facebook.com/asha.verma",
    "https://instagram.com/asha.verma",
    "https://www.instagram.com/asha.verma",
    "https://x.com/asha_verma",
    "https://twitter.com/asha_verma",
    "https://mobile.twitter.com/asha_verma",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BLOCKED_URLS)
async def test_blocked_hosts_are_cannot_check_without_fetching(url):
    fetch, calls = _recording_fetch(200)
    status, evidence, note = await cv.check_link_reachability(url, fetch=fetch)
    assert status == "cannot_check"
    assert evidence == []
    assert "block" in note.lower()
    assert "automated" in note.lower()
    assert calls == []


@pytest.mark.asyncio
async def test_blocked_host_in_full_report_does_not_call_fetch():
    fetch, calls = _recording_fetch(200)
    content = _content(linkedin_url="https://www.linkedin.com/in/asha-verma")
    report = await cv.verify_claims(content, search=_no_search, fetch=fetch)
    links = [c for c in report.checks if c.kind == "link"]
    assert len(links) == 1
    assert links[0].status == "cannot_check"
    assert "block" in links[0].note.lower()
    assert calls == []
    assert report.cannot_check >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://notlinkedin.com/in/asha",
        "https://linkedin.com.example.org/asha",
        "https://github.com/asha",
    ],
)
async def test_lookalike_hosts_still_use_fetch(url):
    fetch, calls = _recording_fetch(200)
    status, _ev, _note = await cv.check_link_reachability(url, fetch=fetch)
    assert status == "found"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,expected", [(200, "found"), (404, "not_found"), (403, "cannot_check")]
)
async def test_other_hosts_use_fetch_result(code, expected):
    fetch, calls = _recording_fetch(code)
    status, _ev, _note = await cv.check_link_reachability("https://example.org/asha", fetch=fetch)
    assert status == expected
    assert len(calls) == 1


# ---------------------------------------------------------------- claim text (A)

def _employer_texts(company: str) -> list[str]:
    content = _content(
        experience=[ResumeExperienceItem(company=company, role_title="Developer")]
    )
    return [c["text"] for c in cv.extract_claims(content) if c["kind"] == "employer"]


@pytest.mark.parametrize("opener", ["(", "["])
def test_unbalanced_trailing_bracket_is_trimmed(opener):
    texts = _employer_texts(f"Quillbyte Labs, Pune {opener}")
    assert len(texts) == 1
    assert not texts[0].rstrip().endswith(opener)
    assert texts[0].startswith("Quillbyte Labs, Pune")
    assert "(" not in texts[0] and "[" not in texts[0]


def test_balanced_parentheses_are_kept():
    texts = _employer_texts("Quillbyte Labs, Pune (Team Lead)")
    assert texts == ["Quillbyte Labs, Pune (Team Lead)"]


def test_balanced_square_brackets_are_kept():
    texts = _employer_texts("Quillbyte Labs [Pune]")
    assert texts == ["Quillbyte Labs [Pune]"]


def test_long_text_is_capped_on_a_word_boundary():
    words = [f"Word{i:02d}" for i in range(40)]
    original = " ".join(words)
    assert len(original) > 120
    texts = _employer_texts(original)
    assert len(texts) == 1
    text = texts[0]
    assert len(text) <= 120
    assert original.startswith(text)
    assert original[len(text)] == " "  # cut between words, never inside one
    assert text == text.rstrip()
    assert text.split(" ")[-1] in words


def test_long_text_cut_ending_in_open_bracket_is_trimmed():
    # Make the 120-char cut land right after an opening parenthesis.
    prefix = "A" * 10 + " " + "B" * 106  # 117 chars
    original = prefix + " (hidden tail words here)"
    texts = _employer_texts(original)
    assert len(texts) == 1
    assert len(texts[0]) <= 120
    assert not texts[0].rstrip().endswith("(")


# ---------------------------------------------------------------- GitHub fake (B)

class RateLimitAfter:
    """Serves canned data for the first `ok_calls` requests, then answers 403 rate-limited."""

    def __init__(self, ok_calls=3, reset_in=None):
        self.ok_calls = ok_calls
        self.reset_in = reset_in  # seconds from now; None means no reset header
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) > self.ok_calls:
            headers = {"x-ratelimit-remaining": "0"}
            if self.reset_in is not None:
                headers["x-ratelimit-reset"] = str(int(time.time() + self.reset_in))
            return httpx.Response(403, json={"message": "rate limited"}, headers=headers)
        parts = [p for p in request.url.path.split("/") if p]
        if parts[0] == "users" and len(parts) == 2:
            return httpx.Response(200, json={"login": parts[1], "public_repos": 2, "type": "User"})
        if parts[0] == "users" and parts[-1] == "repos":
            owner = parts[1]
            return httpx.Response(200, json=[
                {
                    "name": name,
                    "html_url": f"https://github.com/{owner}/{name}",
                    "description": "demo",
                    "language": "Python",
                    "fork": False,
                    "owner": {"login": owner},
                }
                for name in (SECRET_REPO, "second-repo")
            ])
        if parts[0] == "repos" and parts[3] == "languages":
            return httpx.Response(200, json={"Python": 1000})
        if parts[0] == "repos":
            return httpx.Response(200, json=[{"name": "README.md", "type": "file"}])
        return httpx.Response(404, json={})


def _set_env_token(monkeypatch, token):
    fake_settings = SimpleNamespace(GITHUB_TOKEN=token)
    monkeypatch.setattr(backend.config, "get_settings", lambda: fake_settings)
    if hasattr(cg, "get_settings"):
        monkeypatch.setattr(cg, "get_settings", lambda: fake_settings)


def _install(monkeypatch, gh):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(gh.handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr("backend.services.career_github.httpx.AsyncClient", factory)
    return gh


@pytest.fixture(autouse=True)
def _reset_github_state(monkeypatch):
    cache = getattr(cg, "_ANALYSIS_CACHE", None)
    if cache is not None:
        cache.clear()
    monkeypatch.setattr(cg, "_RATE_LIMIT_RESET_AT", 0.0, raising=False)
    _set_env_token(monkeypatch, "")
    yield
    cache = getattr(cg, "_ANALYSIS_CACHE", None)
    if cache is not None:
        cache.clear()


def _limit_warnings(intel):
    return [w for w in intel.warnings if "hourly limit" in w]


def _assert_friendly(intel):
    assert len(_limit_warnings(intel)) == 1
    assert len(intel.warnings) == 1
    text = intel.warnings[0]
    assert "HTTP 403" not in text
    assert "403" not in text
    assert SECRET_REPO not in text
    assert "second-repo" not in text


# ---------------------------------------------------------------- (B) tests

@pytest.mark.asyncio
async def test_midway_rate_limit_adds_one_friendly_warning(monkeypatch):
    gh = _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=25 * 60 + 30))
    intel = await cg.analyze_github_profile("alice")
    assert len(gh.requests) >= 4  # the limit really was hit part-way through
    _assert_friendly(intel)
    text = intel.warnings[0]
    match = re.search(r"resets in about (\d+) minutes", text)
    assert match, text
    assert 24 <= int(match.group(1)) <= 27


@pytest.mark.asyncio
async def test_midway_rate_limit_with_token_mentions_token_limit(monkeypatch):
    _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=20 * 60 + 30))
    intel = await cg.analyze_github_profile("alice", token=FAKE_TOKEN)
    _assert_friendly(intel)
    text = intel.warnings[0]
    assert "token" in text.lower()
    assert "limit" in text.lower()
    assert FAKE_TOKEN not in text
    assert re.search(r"resets in about \d+ minutes", text), text


@pytest.mark.asyncio
async def test_midway_rate_limit_with_env_token_mentions_token_limit(monkeypatch):
    _set_env_token(monkeypatch, FAKE_TOKEN)
    _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=20 * 60 + 30))
    intel = await cg.analyze_github_profile("alice")
    _assert_friendly(intel)
    assert "token" in intel.warnings[0].lower()
    assert FAKE_TOKEN not in intel.warnings[0]


@pytest.mark.asyncio
async def test_midway_rate_limit_without_reset_header_says_under_an_hour(monkeypatch):
    _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=None))
    intel = await cg.analyze_github_profile("alice")
    _assert_friendly(intel)
    assert "in under an hour" in intel.warnings[0]
    assert "resets in about" not in intel.warnings[0]


@pytest.mark.asyncio
async def test_no_token_wording_differs_from_token_wording(monkeypatch):
    _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=20 * 60 + 30))
    anonymous = await cg.analyze_github_profile("alice")
    cg._ANALYSIS_CACHE.clear()
    monkeypatch.setattr(cg, "_RATE_LIMIT_RESET_AT", 0.0, raising=False)
    _install(monkeypatch, RateLimitAfter(ok_calls=3, reset_in=20 * 60 + 30))
    with_token = await cg.analyze_github_profile("alice", token=FAKE_TOKEN)
    assert anonymous.warnings[0] != with_token.warnings[0]
