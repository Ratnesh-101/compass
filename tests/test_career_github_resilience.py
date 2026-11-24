"""Resilience tests for career GitHub analysis: env token, cache, rate-limit cool-down, call budget.

DB-free. All HTTP goes through httpx.MockTransport; the real GitHub is never contacted.
"""
import logging
import re
import time
from types import SimpleNamespace

import httpx
import pytest

import backend.config
import backend.services.career_github as cg

FAKE_ENV_TOKEN = "ghp_FAKE_ENV_TOKEN_000"
FAKE_CALLER_TOKEN = "ghp_FAKE_CALLER_TOKEN_000"
REAL_ASYNC_CLIENT = httpx.AsyncClient


def _repo(name, owner):
    return {
        "name": name,
        "html_url": f"https://github.com/{owner}/{name}",
        "description": f"{name} project",
        "language": "Python",
        "fork": False,
        "owner": {"login": owner},
    }


class FakeGitHub:
    """Request counter plus canned JSON. Behaviour is switched through attributes."""

    def __init__(self, repo_count=2):
        self.repo_count = repo_count
        self.requests = []
        self.rate_limit = None  # (status, reset_epoch) applied to every request when set

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.rate_limit:
            status, reset = self.rate_limit
            return httpx.Response(
                status,
                json={"message": "rate limited"},
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(reset))},
            )
        path = request.url.path
        parts = [p for p in path.split("/") if p]
        if parts[0] == "users" and len(parts) == 2:
            return httpx.Response(200, json={"login": parts[1], "public_repos": self.repo_count,
                                             "type": "User"})
        if parts[0] == "users" and parts[-1] == "repos":
            owner = parts[1]
            return httpx.Response(200, json=[_repo(f"r{i}", owner) for i in range(self.repo_count)])
        if parts[0] == "repos":
            if parts[3] == "languages":
                return httpx.Response(200, json={"Python": 1000})
            rel = "/".join(parts[4:])  # after "contents"
            if rel == "":
                # Dirs that force extra detail calls (tests dir, workflows, circleci).
                return httpx.Response(200, json=[
                    {"name": "README.md", "type": "file"},
                    {"name": "tests", "type": "dir"},
                    {"name": ".github", "type": "dir"},
                    {"name": ".circleci", "type": "dir"},
                ])
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    @property
    def count(self):
        return len(self.requests)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    cache = getattr(cg, "_ANALYSIS_CACHE", None)
    if cache is not None:
        cache.clear()
    monkeypatch.setattr(cg, "_RATE_LIMIT_RESET_AT", 0.0, raising=False)
    set_env_token(monkeypatch, "")
    yield
    cache = getattr(cg, "_ANALYSIS_CACHE", None)
    if cache is not None:
        cache.clear()


def set_env_token(monkeypatch, token):
    fake_settings = SimpleNamespace(GITHUB_TOKEN=token)
    monkeypatch.setattr(backend.config, "get_settings", lambda: fake_settings)
    if hasattr(cg, "get_settings"):  # in case the module binds it at import time
        monkeypatch.setattr(cg, "get_settings", lambda: fake_settings)


def install(monkeypatch, gh):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(gh.handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr("backend.services.career_github.httpx.AsyncClient", factory)
    return gh


def auth_headers(gh):
    return [r.headers.get("authorization") for r in gh.requests]


# ---------- (1) env token fallback ----------

@pytest.mark.asyncio
async def test_env_token_used_when_caller_passes_none(monkeypatch, caplog):
    set_env_token(monkeypatch, FAKE_ENV_TOKEN)
    gh = install(monkeypatch, FakeGitHub())
    with caplog.at_level(logging.DEBUG):
        intel = await cg.analyze_github_profile("alice")
    assert gh.count > 0
    assert set(auth_headers(gh)) == {f"Bearer {FAKE_ENV_TOKEN}"}
    assert all(r.url.host == "api.github.com" for r in gh.requests)
    assert FAKE_ENV_TOKEN not in intel.model_dump_json()
    assert FAKE_ENV_TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_caller_token_wins_over_env_token(monkeypatch, caplog):
    set_env_token(monkeypatch, FAKE_ENV_TOKEN)
    gh = install(monkeypatch, FakeGitHub())
    with caplog.at_level(logging.DEBUG):
        intel = await cg.analyze_github_profile("alice", token=FAKE_CALLER_TOKEN)
    assert set(auth_headers(gh)) == {f"Bearer {FAKE_CALLER_TOKEN}"}
    dumped = intel.model_dump_json()
    for secret in (FAKE_CALLER_TOKEN, FAKE_ENV_TOKEN):
        assert secret not in dumped
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_no_authorization_header_without_any_token(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    await cg.analyze_github_profile("alice")
    assert gh.count > 0
    assert set(auth_headers(gh)) == {None}


@pytest.mark.asyncio
async def test_env_token_not_leaked_in_warnings_on_rate_limit(monkeypatch, caplog):
    set_env_token(monkeypatch, FAKE_ENV_TOKEN)
    gh = install(monkeypatch, FakeGitHub())
    gh.rate_limit = (403, time.time() + 600)
    with caplog.at_level(logging.DEBUG):
        intel = await cg.analyze_github_profile("alice")
    assert intel.warnings
    assert FAKE_ENV_TOKEN not in " ".join(intel.warnings)
    assert FAKE_ENV_TOKEN not in caplog.text


# ---------- (2) cache ----------

@pytest.mark.asyncio
async def test_fresh_cache_hit_makes_zero_http_calls(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    first = await cg.analyze_github_profile("Alice")
    assert first.status in ("ok", "partial")
    made = gh.count
    assert made > 0

    second = await cg.analyze_github_profile("alice")  # same key, lowercase
    assert gh.count == made
    assert any(re.search(r"Showing the result from \d+ minutes? ago\.", w) for w in second.warnings)
    assert second.username == first.username
    assert second.detected_skills == first.detected_skills


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    await cg.analyze_github_profile("alice")
    made = gh.count
    fresh = await cg.analyze_github_profile("alice", force_refresh=True)
    assert gh.count > made
    assert not any("Showing the result from" in w for w in fresh.warnings)


@pytest.mark.asyncio
async def test_failed_results_are_not_cached(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    gh.rate_limit = (429, time.time() + 600)
    failed = await cg.analyze_github_profile("alice", token=FAKE_CALLER_TOKEN)
    assert failed.status == "failed"
    gh.rate_limit = None
    made = gh.count
    again = await cg.analyze_github_profile("alice", token=FAKE_CALLER_TOKEN)
    assert gh.count > made
    assert again.status in ("ok", "partial")


# ---------- (3) rate-limit cool-down ----------

@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.asyncio
async def test_rate_limit_records_reset_time(monkeypatch, status):
    gh = install(monkeypatch, FakeGitHub())
    reset = int(time.time()) + 900
    gh.rate_limit = (status, reset)
    await cg.analyze_github_profile("alice")
    assert cg._RATE_LIMIT_RESET_AT == pytest.approx(reset, abs=1)


@pytest.mark.asyncio
async def test_cooldown_without_cache_returns_failed_with_single_warning(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    gh.rate_limit = (403, time.time() + 900)
    await cg.analyze_github_profile("alice")
    made = gh.count
    assert cg._RATE_LIMIT_RESET_AT > time.time()

    intel = await cg.analyze_github_profile("bob")
    assert gh.count == made  # zero HTTP during the cool-down
    assert intel.status == "failed"
    assert len(intel.warnings) == 1
    assert "resets in about" in intel.warnings[0]
    assert "personal access token" in intel.warnings[0]


@pytest.mark.asyncio
async def test_cooldown_with_cache_returns_stale_result(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    good = await cg.analyze_github_profile("alice")
    assert good.status in ("ok", "partial")

    gh.rate_limit = (403, time.time() + 900)
    limited = await cg.analyze_github_profile("alice", force_refresh=True)
    assert limited.status in ("ok", "partial")
    assert limited.detected_skills == good.detected_skills
    assert any("last saved result" in w for w in limited.warnings)
    assert cg._RATE_LIMIT_RESET_AT > time.time()
    made = gh.count

    stale = await cg.analyze_github_profile("alice")
    assert gh.count == made
    assert stale.status in ("ok", "partial")
    assert stale.detected_skills == good.detected_skills
    assert any("last saved result" in w for w in stale.warnings)


@pytest.mark.asyncio
async def test_token_call_ignores_cooldown(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    gh.rate_limit = (403, time.time() + 900)
    await cg.analyze_github_profile("alice")
    gh.rate_limit = None
    made = gh.count

    intel = await cg.analyze_github_profile("bob", token=FAKE_CALLER_TOKEN)
    assert gh.count > made
    assert intel.status in ("ok", "partial")


@pytest.mark.asyncio
async def test_env_token_also_ignores_cooldown(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    gh.rate_limit = (429, time.time() + 900)
    await cg.analyze_github_profile("alice")
    gh.rate_limit = None
    made = gh.count

    set_env_token(monkeypatch, FAKE_ENV_TOKEN)
    intel = await cg.analyze_github_profile("bob")
    assert gh.count > made
    assert intel.status in ("ok", "partial")


@pytest.mark.asyncio
async def test_expired_cooldown_allows_calls(monkeypatch):
    gh = install(monkeypatch, FakeGitHub())
    monkeypatch.setattr(cg, "_RATE_LIMIT_RESET_AT", time.time() - 5, raising=False)
    intel = await cg.analyze_github_profile("alice")
    assert gh.count > 0
    assert intel.status in ("ok", "partial")


# ---------- (4) call budget ----------

@pytest.mark.asyncio
async def test_budget_is_12_without_token(monkeypatch):
    gh = install(monkeypatch, FakeGitHub(repo_count=8))
    intel = await cg.analyze_github_profile("alice")
    assert gh.count <= 12
    assert gh.count >= 10  # the budget is actually the limiting factor
    assert intel.warnings  # truncation is reported, not silent


@pytest.mark.asyncio
async def test_budget_up_to_25_with_token(monkeypatch):
    gh = install(monkeypatch, FakeGitHub(repo_count=8))
    await cg.analyze_github_profile("alice", token=FAKE_CALLER_TOKEN)
    assert 12 < gh.count <= 25


@pytest.mark.asyncio
async def test_budget_up_to_25_with_env_token(monkeypatch):
    set_env_token(monkeypatch, FAKE_ENV_TOKEN)
    gh = install(monkeypatch, FakeGitHub(repo_count=8))
    await cg.analyze_github_profile("alice")
    assert 12 < gh.count <= 25
