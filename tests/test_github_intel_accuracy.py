"""Accuracy and failure-visibility tests for GitHub Intelligence (httpx mocked, no network)."""
import logging
import pathlib
from unittest.mock import patch

import httpx
import pytest

from backend.services.career_github import analyze_github_profile

SECRET_TOKEN = "ghp_SUPERSECRETTOKENVALUE1234567890"
ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeResp:
    def __init__(self, data=None, status=200, headers=None):
        self._data = data
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._data


def repo(name, lang="Python", fork=False, owner="alice"):
    return {
        "name": name,
        "html_url": f"https://github.com/{owner}/{name}",
        "description": f"{name} project",
        "language": lang,
        "fork": fork,
        "owner": {"login": owner},
    }


def make_get(repos, languages=None, contents=None, user_status=200, repos_status=200,
             default_contents=None, user_extra=None, calls=None):
    """Build a fake AsyncClient.get routing on the URL path."""
    languages = languages or {}
    contents = contents or {}

    async def fake_get(url, *args, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        path = url.replace("https://api.github.com", "")
        if path.startswith("/users/") and path.endswith("/repos"):
            return FakeResp(repos, repos_status)
        if path.startswith("/users/"):
            body = {"login": "alice", "public_repos": len(repos), "type": "User"}
            body.update(user_extra or {})
            return FakeResp(body, user_status)
        if path.endswith("/languages"):
            name = path.split("/")[3]
            val = languages.get(name, {})
            if isinstance(val, int):
                return FakeResp({}, val)
            return FakeResp(val)
        if "/contents" in path:
            rel = path.split("/contents", 1)[1].lstrip("/")
            name = path.split("/")[3]
            key = (name, rel)
            if key in contents:
                val = contents[key]
                if isinstance(val, int):
                    return FakeResp({}, val)
                return FakeResp(val)
            if rel == "":
                return FakeResp(default_contents if default_contents is not None else [])
            return FakeResp({}, 404)
        return FakeResp({}, 404)

    return fake_get


async def run(repos, **kw):
    token = kw.pop("token", None)
    get = make_get(repos, **kw)
    with patch("httpx.AsyncClient.get", side_effect=get):
        return await analyze_github_profile("alice", token=token)


def files(*names):
    return [{"name": n, "type": "file"} for n in names]


def dirs(*names):
    return [{"name": n, "type": "dir"} for n in names]


@pytest.mark.asyncio
async def test_skills_only_from_owned_repos():
    repos = [repo("mine", "Python"), repo("theirs", "Rust", fork=True)]
    intel = await run(
        repos,
        languages={"mine": {"Python": 9000}, "theirs": {"Rust": 99999}},
        contents={("mine", ""): files("README.md")},
    )
    assert "Python" in intel.detected_skills
    assert "Rust" not in intel.detected_skills


@pytest.mark.asyncio
async def test_byte_share_threshold_drops_tiny_languages():
    repos = [repo("mine", "Python")]
    intel = await run(
        repos,
        languages={"mine": {"Python": 96000, "Go": 2000, "Lua": 2000}},
        contents={("mine", ""): files("README.md")},
    )
    assert intel.detected_skills == ["Python"]


@pytest.mark.asyncio
async def test_markup_and_config_languages_ignored():
    repos = [repo("mine", "Python")]
    langs = {"Python": 5000, "HTML": 5000, "CSS": 5000, "Shell": 5000, "Dockerfile": 5000,
             "Makefile": 5000, "Jupyter Notebook": 5000}
    intel = await run(repos, languages={"mine": langs},
                      contents={("mine", ""): files("README.md")})
    assert intel.detected_skills == ["Python"]


@pytest.mark.asyncio
async def test_fork_excluded_from_budget_and_has_no_per_repo_calls():
    forks = [repo(f"fork{i}", "Rust", fork=True) for i in range(10)]
    owned = [repo(f"own{i}", "Python") for i in range(8)]
    calls = []
    langs = {f"own{i}": {"Python": 100} for i in range(8)}
    intel = await run(forks + owned, languages=langs, calls=calls,
                      default_contents=files("README.md"))
    analyzed_owned = [r for r in intel.analyzed_repos if r.is_owned]
    assert len(analyzed_owned) == 8
    assert not any("/repos/alice/fork" in u for u, _ in calls)
    assert len(calls) <= 25
    forks_out = [r for r in intel.analyzed_repos if r.is_fork]
    assert forks_out
    for r in forks_out:
        assert not any("Core codebase" in e for e in r.implementation_evidence)
        assert r.has_tests is None and r.has_ci_cd is None


@pytest.mark.asyncio
async def test_core_codebase_text_only_for_owned():
    intel = await run([repo("mine", "Python")], languages={"mine": {"Python": 10}},
                      default_contents=files("README.md"))
    assert any("Core codebase" in e for e in intel.analyzed_repos[0].implementation_evidence)


@pytest.mark.parametrize(
    "root,extra,expected",
    [
        (files("Dockerfile", "docker-compose.yml"), {}, False),
        (dirs(".github"), {("r", ".github/workflows"): 404}, False),
        (dirs(".github"), {("r", ".github/workflows"): []}, False),
        (dirs(".github"), {("r", ".github/workflows"): files("ci.yml")}, True),
        (files(".gitlab-ci.yml"), {}, True),
        (files("Jenkinsfile"), {}, True),
        (dirs(".circleci"), {("r", ".circleci"): files("config.yml")}, True),
    ],
)
@pytest.mark.asyncio
async def test_ci_detection_cases(root, extra, expected):
    contents = {("r", ""): root}
    contents.update(extra)
    intel = await run([repo("r")], languages={"r": {"Python": 10}}, contents=contents)
    assert intel.analyzed_repos[0].has_ci_cd is expected


@pytest.mark.asyncio
async def test_tests_detection_requires_nonempty_dir_or_test_files():
    empty = await run([repo("r")], languages={"r": {"Python": 10}},
                      contents={("r", ""): dirs("tests"), ("r", "tests"): []})
    assert empty.analyzed_repos[0].has_tests is False
    full = await run([repo("r")], languages={"r": {"Python": 10}},
                     contents={("r", ""): dirs("tests"), ("r", "tests"): files("test_a.py")})
    assert full.analyzed_repos[0].has_tests is True
    named = await run([repo("r")], languages={"r": {"Python": 10}},
                      contents={("r", ""): files("test_app.py")})
    assert named.analyzed_repos[0].has_tests is True
    cfg = await run([repo("r")], languages={"r": {"Python": 10}},
                    contents={("r", ""): files("pytest.ini", "jest.config.js")})
    assert cfg.analyzed_repos[0].has_tests is False


@pytest.mark.asyncio
async def test_unknown_none_when_contents_rate_limited():
    intel = await run([repo("r")], languages={"r": {"Python": 10}},
                      contents={("r", ""): 403})
    r = intel.analyzed_repos[0]
    assert r.has_tests is None and r.has_ci_cd is None
    assert not any("No explicit automated test suite" in x for x in r.limitations)
    assert intel.warnings


@pytest.mark.asyncio
async def test_warning_on_user_404():
    intel = await run([], user_status=404)
    assert intel.warnings and "not found" in intel.warnings[0].lower()
    assert intel.status == "failed"


@pytest.mark.asyncio
async def test_warning_on_user_403_rate_limit():
    intel = await run([], user_status=403)
    assert any("rate limit" in w.lower() for w in intel.warnings)
    assert intel.status == "failed"


@pytest.mark.asyncio
async def test_warning_on_5xx_repos_list():
    intel = await run([repo("r")], repos_status=503)
    assert any("503" in w for w in intel.warnings)
    assert intel.status == "failed"


@pytest.mark.asyncio
async def test_warning_on_languages_5xx():
    intel = await run([repo("r")], languages={"r": 500},
                      contents={("r", ""): files("README.md")})
    assert any("500" in w and "language" in w.lower() for w in intel.warnings)
    assert intel.status == "partial"


@pytest.mark.asyncio
async def test_token_never_logged_or_returned_and_uses_bearer(caplog):
    calls = []
    get = make_get([repo("r")], languages={"r": 403}, contents={("r", ""): 403}, calls=calls)
    real_init = httpx.AsyncClient.__init__
    captured = {}

    def spy_init(self, *a, **kw):
        captured.update(kw.get("headers", {}))
        real_init(self, *a, **kw)

    with caplog.at_level(logging.DEBUG), \
            patch("httpx.AsyncClient.__init__", spy_init), \
            patch("httpx.AsyncClient.get", side_effect=get):
        intel = await analyze_github_profile("alice", token=SECRET_TOKEN)
    assert captured.get("Authorization") == f"Bearer {SECRET_TOKEN}"
    assert all(u.startswith("https://api.github.com/") for u, _ in calls)
    assert SECRET_TOKEN not in intel.model_dump_json()
    assert SECRET_TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_token_not_leaked_when_request_raises(caplog):
    async def boom(url, *a, **kw):
        raise RuntimeError(f"connect failed with header Bearer {SECRET_TOKEN}")

    with caplog.at_level(logging.DEBUG), patch("httpx.AsyncClient.get", side_effect=boom):
        intel = await analyze_github_profile("alice", token=SECRET_TOKEN)
    assert SECRET_TOKEN not in intel.model_dump_json()
    assert SECRET_TOKEN not in caplog.text
    assert intel.warnings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("alice", "alice"),
        ("@alice", "alice"),
        ("https://github.com/alice", "alice"),
        ("github.com/alice/repo", "alice"),
        ("https://www.github.com/alice/", "alice"),
        ("  Alice-Dev  ", "Alice-Dev"),
    ],
)
def test_username_normalisation_ok(raw, expected):
    from backend.services.career_github import parse_github_username

    assert parse_github_username(raw) == (expected, None)


@pytest.mark.parametrize(
    "raw",
    ["", "-alice", "alice-", "al--ice", "https://github.com/orgs/acme", "https://evil.com/alice",
     "https://github.com/settings", "a b", "alice/../x", "x" * 40],
)
def test_username_normalisation_rejects(raw):
    from backend.services.career_github import parse_github_username

    name, err = parse_github_username(raw)
    assert name is None and err


@pytest.mark.asyncio
async def test_invalid_input_not_echoed_into_profile_url():
    intel = await analyze_github_profile("https://evil.com/<script>alert(1)</script>")
    assert "script" not in intel.profile_url and "evil" not in intel.profile_url
    assert intel.warnings and intel.status == "failed"


@pytest.mark.asyncio
async def test_organization_rejected():
    intel = await run([], user_extra={"type": "Organization"})
    assert intel.status == "failed"
    assert any("organi" in w.lower() for w in intel.warnings)


def test_modal_renders_warnings_and_new_wording():
    src = (ROOT / "frontend/src/components/career/GitHubIntelligenceModal.jsx").read_text(encoding="utf8")
    assert "intel.warnings" in src
    assert "Technologies detected in your own repositories" in src
    assert "Detected from repository metadata" in src
    assert "Verified Technologies" not in src
    assert "or private repos" not in src
    assert "Fork - not your original work" in src
