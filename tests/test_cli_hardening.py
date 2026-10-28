"""
Compass CLI hardening tests: exit codes, streaming retries, HTTP error handling,
auth precedence, config file handling, URL encoding and stdio setup.

These tests exercise the real _get/_post/_stream_chat with httpx monkeypatched
(no network, no running backend).
"""

import json
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from cli import assistant_cli
from cli.assistant_cli import app

runner = CliRunner()

LOCAL_URL = "http://localhost:8000"
REQUEST = httpx.Request("GET", f"{LOCAL_URL}/x")


@pytest.fixture(autouse=True)
def isolated_cli(monkeypatch, tmp_path):
    """Point CLI config/credentials at tmp_path and seed a guest identity."""
    monkeypatch.setattr(assistant_cli, "CONFIG_DIR", tmp_path / ".compass")
    monkeypatch.setattr(assistant_cli, "CONFIG_FILE", tmp_path / ".compass" / "config.toml")
    monkeypatch.setattr(assistant_cli, "CREDENTIALS_FILE", tmp_path / ".compass" / "credentials.json")
    monkeypatch.setattr(assistant_cli, "API_BASE", LOCAL_URL)
    for name in ("AUTH_TOKEN", "COMPASS_AUTH_TOKEN", "GUEST_TOKEN", "GUEST_ID", "COMPASS_SESSION", "COMPASS_API_URL"):
        monkeypatch.delenv(name, raising=False)
    assistant_cli.save_credentials({"guest_id": "g1", "guest_token": "g1.1700000000.sig"})


def http_response(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {"detail": "boom"}, request=REQUEST)


def patch_http(monkeypatch, status: int = 200, body: dict | None = None, exc: Exception | None = None):
    """Make httpx.get/post return a canned response or raise exc."""
    calls: list[tuple[str, dict]] = []

    def fake(url, *args, **kwargs):
        calls.append((url, kwargs))
        if exc is not None:
            raise exc
        return http_response(status, body)

    monkeypatch.setattr(httpx, "get", fake)
    monkeypatch.setattr(httpx, "post", fake)
    return calls


def combined(result) -> str:
    return (result.stdout or "") + (result.stderr or "")


# ---------------------------------------------------------------------------
# 1. typer.Exit must not be swallowed by broad except blocks
# ---------------------------------------------------------------------------

def test_consolidate_http_error_is_not_reported_as_empty_failure(monkeypatch):
    patch_http(monkeypatch, status=500)
    result = runner.invoke(app, ["admin", "consolidate", "--token", "adm"])
    assert result.exit_code == 1
    assert "500" in combined(result)
    assert "Failed to" not in combined(result)
    assert "request failed" not in combined(result)


def test_agent_activity_http_error_message_not_duplicated(monkeypatch):
    patch_http(monkeypatch, status=503)
    result = runner.invoke(app, ["agent-activity"])
    assert result.exit_code == 1
    assert "503" in combined(result)
    assert "Failed to" not in combined(result)


def test_agent_undo_non_ok_status_exits_nonzero(monkeypatch):
    patch_http(monkeypatch, body={"status": "error", "message": "Nothing to undo"})
    result = runner.invoke(app, ["agent-undo", "--run-id", "r1"])
    assert result.exit_code == 1
    assert "Nothing to undo" in combined(result)


def test_agent_undo_http_error_exits_nonzero(monkeypatch):
    patch_http(monkeypatch, status=500)
    result = runner.invoke(app, ["agent-undo"])
    assert result.exit_code == 1
    assert "Failed to" not in combined(result)


# ---------------------------------------------------------------------------
# 2. _stream_chat must not re-POST once the server may have acted
# ---------------------------------------------------------------------------

class FakeStream:
    def __init__(self, lines=(), status_code=200, raise_after=None):
        self.status_code = status_code
        self._lines = list(lines)
        self._raise_after = raise_after
        self.request = REQUEST
        self.headers = {}
        self.text = json.dumps({"detail": "denied"})

    def read(self):
        return b""

    def json(self):
        return {"detail": "denied"}

    def iter_lines(self):
        yield from self._lines
        if self._raise_after is not None:
            raise self._raise_after

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def token_line(value: str) -> str:
    return "data: " + json.dumps({"type": "token", "value": value})


def count_post_calls(monkeypatch) -> list:
    calls: list = []

    def fake_post(path, data, headers=None):
        calls.append(path)
        return {"response": "fallback", "conversation_id": "c", "skill_used": None}

    monkeypatch.setattr(assistant_cli, "_post", fake_post)
    return calls


def test_stream_remote_protocol_error_midstream_exits_without_retry(monkeypatch):
    posts = count_post_calls(monkeypatch)
    err = httpx.RemoteProtocolError("peer closed connection")
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream([token_line("Added ")], raise_after=err))
    result = runner.invoke(app, ["ask", "add task X"])
    assert posts == []
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # clean exit, not a traceback


def test_stream_read_timeout_before_any_output_does_not_repost(monkeypatch):
    posts = count_post_calls(monkeypatch)
    err = httpx.ReadTimeout("timed out")
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream([], raise_after=err))
    result = runner.invoke(app, ["ask", "add task X"])
    assert posts == []
    assert result.exit_code == 1


def test_stream_non_200_surfaces_error_once_without_retry(monkeypatch):
    posts = count_post_calls(monkeypatch)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream(status_code=401))
    result = runner.invoke(app, ["ask", "hello"])
    assert posts == []
    assert result.exit_code == 1
    assert "401" in combined(result)


def test_stream_sse_error_event_exits_nonzero_without_retry(monkeypatch):
    posts = count_post_calls(monkeypatch)
    lines = ["data: " + json.dumps({"type": "error", "message": "model unavailable"})]
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream(lines))
    result = runner.invoke(app, ["ask", "hello"])
    assert posts == []
    assert result.exit_code == 1
    assert "model unavailable" in combined(result)


def test_stream_connect_error_falls_back_exactly_once(monkeypatch):
    posts = count_post_calls(monkeypatch)

    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "stream", refuse)
    result = runner.invoke(app, ["ask", "hello"])
    assert result.exit_code == 0
    assert posts == ["/api/chat"]
    assert "fallback" in result.stdout


# ---------------------------------------------------------------------------
# 3. _post / _get handle every httpx error with a friendly message
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    httpx.ReadTimeout("slow"),
    httpx.RemoteProtocolError("closed"),
    httpx.ReadError("reset"),
])
def test_post_transport_errors_exit_cleanly(monkeypatch, exc):
    patch_http(monkeypatch, exc=exc)
    result = runner.invoke(app, ["add", "T"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Cannot connect" in combined(result)


def test_post_invalid_json_exits_cleanly(monkeypatch):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("not json")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: resp)
    result = runner.invoke(app, ["add", "T"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)


# ---------------------------------------------------------------------------
# 4. Auth precedence
# ---------------------------------------------------------------------------

def test_saved_credentials_win_over_env_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "env-token")
    headers = assistant_cli._headers()
    assert headers["Authorization"] == "Bearer g1.1700000000.sig"


def test_env_token_used_when_nothing_saved(monkeypatch):
    assistant_cli.CREDENTIALS_FILE.unlink()
    monkeypatch.setenv("AUTH_TOKEN", "env-token")
    assert assistant_cli._headers()["Authorization"] == "Bearer env-token"


@pytest.mark.parametrize("base", ["http://localhost:8000", "https://api.example.com"])
def test_no_token_never_falls_back_to_dev_token(monkeypatch, base):
    assistant_cli.CREDENTIALS_FILE.unlink()
    monkeypatch.setattr(assistant_cli, "API_BASE", base)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("no request should be sent without a token"))
    result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 1
    assert "Not authenticated" in combined(result)


# ---------------------------------------------------------------------------
# 5. Config file
# ---------------------------------------------------------------------------

def test_save_config_escapes_special_characters():
    nasty = 'http://host/"quote"\\back'
    assistant_cli.save_config(nasty)
    parsed = tomllib.loads(assistant_cli.CONFIG_FILE.read_text(encoding="utf-8"))
    assert parsed["api_url"] == nasty
    assert assistant_cli.load_config() == nasty


def test_save_config_restricts_permissions(monkeypatch):
    secured: list[Path] = []
    monkeypatch.setattr(assistant_cli, "_secure_file_permissions", lambda p: secured.append(p))
    assistant_cli.save_config("http://localhost:8000")
    assert secured == [assistant_cli.CONFIG_FILE]


def test_corrupt_config_warns_instead_of_silently_defaulting(capsys):
    assistant_cli.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    assistant_cli.CONFIG_FILE.write_text('api_url = "unterminated\n', encoding="utf-8")
    assert assistant_cli.load_config() == "http://localhost:8000"
    assert "Warning" in capsys.readouterr().err


def test_config_display_does_not_reveal_token_length():
    assistant_cli.save_credentials({"guest_id": "g1", "guest_token": "t" * 57})
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "[CONFIGURED]" in result.stdout
    assert "57" not in result.stdout
    assert "ttt" not in result.stdout


# ---------------------------------------------------------------------------
# 6. Query params are URL-encoded by httpx
# ---------------------------------------------------------------------------

def test_agent_runs_passes_conversation_id_as_param(monkeypatch):
    calls = patch_http(monkeypatch, body={"runs": []})
    cid = "a&limit=999 b#frag"
    result = runner.invoke(app, ["agent-runs", "-c", cid, "-n", "5"])
    assert result.exit_code == 0
    url, kwargs = calls[0]
    assert "?" not in url and "&" not in url
    assert kwargs["params"] == {"limit": 5, "conversation_id": cid}


def test_agent_activity_passes_limit_as_param(monkeypatch):
    calls = patch_http(monkeypatch, body={"activity": []})
    result = runner.invoke(app, ["agent-activity", "-n", "7"])
    assert result.exit_code == 0
    url, kwargs = calls[0]
    assert "?" not in url
    assert kwargs["params"] == {"limit": 7}


# ---------------------------------------------------------------------------
# 7. stdio reconfigure guard
# ---------------------------------------------------------------------------

def test_configure_stdio_tolerates_streams_without_reconfigure():
    class Plain:
        pass

    recorded = MagicMock()
    assistant_cli._configure_stdio((Plain(), recorded))
    recorded.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 8. recap / add must not report success on failure
# ---------------------------------------------------------------------------

def test_recap_conversation_list_http_error_is_not_no_conversation(monkeypatch):
    patch_http(monkeypatch, status=500)
    result = runner.invoke(app, ["recap"])
    assert result.exit_code == 1
    assert "No conversation found" not in combined(result)
    assert "500" in combined(result)


@pytest.mark.parametrize("reply", [
    {"status": "error", "message": "db down"},
    {"error": "validation failed"},
    {},
])
def test_add_does_not_print_success_when_backend_reports_failure(monkeypatch, reply):
    monkeypatch.setattr(assistant_cli, "_post", lambda *a, **k: reply)
    result = runner.invoke(app, ["add", "T"])
    assert result.exit_code == 1
    assert "Task created successfully" not in combined(result)


# ---------------------------------------------------------------------------
# 9. Packaging metadata
# ---------------------------------------------------------------------------

def test_cli_pyproject_declares_cli_packages():
    root = Path(__file__).resolve().parents[1] / "cli"
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools_cfg = data["tool"]["setuptools"]
    assert setuptools_cfg["package-dir"] == {"cli": "."}
    assert setuptools_cfg["packages"] == ["cli", "cli.commands"]
    assert (root / "commands" / "__init__.py").exists()
    assert data["project"]["scripts"]["compass"] == "cli.assistant_cli:app"
