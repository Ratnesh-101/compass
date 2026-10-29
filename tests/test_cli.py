"""
Compass — CLI Command Tests via Typer CliRunner.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import httpx
import pytest
from typer.testing import CliRunner
from cli.assistant_cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_cli_network(monkeypatch, tmp_path):
    """Hermetically mock CLI HTTP calls and credentials directory so tests don't pollute user home."""
    from cli import assistant_cli

    # Redirect config and credentials to tmp_path
    monkeypatch.setattr(assistant_cli, "CONFIG_DIR", tmp_path / ".compass")
    monkeypatch.setattr(assistant_cli, "CONFIG_FILE", tmp_path / ".compass" / "config.toml")
    monkeypatch.setattr(assistant_cli, "CREDENTIALS_FILE", tmp_path / ".compass" / "credentials.json")
    monkeypatch.setattr(assistant_cli, "API_BASE", "http://localhost:8000")

    # Set initial test guest credentials
    test_creds = {
        "guest_id": "test-guest-uuid-1234",
        "guest_token": "test-guest-uuid-1234.1700000000.testsig",
    }
    assistant_cli.save_credentials(test_creds)

    def mock_get(path: str, params: dict | None = None, headers: dict | None = None) -> dict:
        if "/dashboard" in path:
            return {
                "domains": {
                    "hackathon": {
                        "project_count": 2,
                        "open_task_count": 4,
                        "nearest_deadline": {"title": "AI Hackathon Milestone", "due_date": "2026-09-21"},
                    },
                    "coursework": {
                        "project_count": 3,
                        "open_task_count": 2,
                        "nearest_deadline": {"title": "OS Homework 2", "due_date": "2026-09-22"},
                    },
                    "code": {
                        "project_count": 1,
                        "open_task_count": 1,
                        "nearest_deadline": None,
                    },
                },
                "total_open_tasks": 7,
                "total_projects": 6,
            }
        elif "/projects" in path:
            return {
                "projects": [
                    {"id": 1, "name": "AI Hackathon", "domain": "hackathon", "status": "active"},
                    {"id": 2, "name": "Operating Systems", "domain": "coursework", "status": "active"},
                    {"id": 3, "name": "Compass Engine", "domain": "code", "status": "active"},
                ]
            }
        elif "/tasks" in path:
            return {
                "tasks": [
                    {
                        "id": 101,
                        "title": "Complete PRD Implementation",
                        "domain": "hackathon",
                        "status": "open",
                        "priority": "high",
                        "due_date": "2026-09-21",
                        "project": {"name": "AI Hackathon"},
                    }
                ]
            }
        elif "/admin/usage" in path:
            return {
                "models": [{"model": "nvidia/nemotron", "tokens": 1200, "cost": 0.002}],
                "total_cost": 0.002,
            }
        elif "/api/agent/activity" in path:
            return {"activity": [{"id": 1, "action": "delete_task", "status": "success"}]}
        elif "/api/agent/runs" in path:
            return {"runs": [{"run_id": "run_1", "status": "completed", "steps": 3}]}
        elif "/api/agent/critique-stats" in path:
            return {"total_critiques": 5, "improved_plans": 4}
        elif "/api/agent/proactive-briefing" in path:
            return {"briefing": "Good morning. 2 deadlines today."}
        return {}

    def mock_post(path: str, data: dict, headers: dict | None = None) -> dict:
        if "/api/log" in path or "/memory/log" in path:
            return {
                "status": "ok",
                "message": "Memory logged successfully",
                "entry_id": 42,
            }
        elif "/tasks" in path:
            return {
                "id": 102,
                "title": data.get("title", ""),
                "domain": data.get("domain", "general"),
            }
        elif "/chat" in path:
            return {
                "response": "Added task: CLI REPL verification task\nwhen is it due? It is due on 2026-09-21.",
                "conversation_id": "conv_repl_123",
                "skill_used": "add_task",
            }
        elif "/api/agent/undo" in path:
            return {"status": "ok", "message": "Successfully reverted last mutation", "reverted": "Task #101 restored"}
        elif "/admin/consolidate" in path:
            return {"overdue_tasks_flagged": 2, "duplicate_chunks_merged": 1, "stale_conversations_rolled_up": 0}
        return {}

    def mock_stream_chat(payload: dict) -> tuple[str, str | None, str | None]:
        msg = payload.get("message", "")
        if "add a task" in msg.lower():
            resp = "Added task: CLI REPL verification task"
        else:
            resp = "Task deadline is 2026-09-21."
        assistant_cli.console.print(resp)
        return resp, "conv_repl_123", "add_task"

    monkeypatch.setattr(assistant_cli, "_get", mock_get)
    monkeypatch.setattr(assistant_cli, "_post", mock_post)
    monkeypatch.setattr(assistant_cli, "_stream_chat", mock_stream_chat)


def test_cli_help():
    """Verify `compass --help` prints usage instructions."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Compass" in result.stdout
    assert "status" in result.stdout
    assert "tasks" in result.stdout
    assert "login" in result.stdout


def test_cli_version():
    """Verify `compass --version` prints version string and exits cleanly."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "Compass CLI 0.1.0" in result.stdout


def test_cli_login_mint_guest(monkeypatch):
    """Verify `compass login` fetches caller's own signed guest identity and saves masked."""
    from cli import assistant_cli

    def mock_post_mint(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "status": "ok",
            "guest_id": "guest_abc_123",
            "guest_token": "guest_abc_123.1700000000.hmacsig",
        }
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("httpx.post", mock_post_mint)
    result = runner.invoke(app, ["login", "--url", "http://localhost:8000"])
    assert result.exit_code == 0
    assert "Logged in successfully" in result.stdout
    assert "guest_ab" in result.stdout
    assert "[CONFIGURED]" in result.stdout

    creds = assistant_cli.load_credentials()
    assert creds["guest_id"] == "guest_abc_123"
    assert creds["guest_token"] == "guest_abc_123.1700000000.hmacsig"


def test_cli_headers_isolation(monkeypatch):
    """Verify normal commands use guest token and admin commands use master token."""
    from cli import assistant_cli
    # Normal commands
    normal_h = assistant_cli._headers(admin=False)
    assert "x-guest-token" in normal_h
    assert normal_h["x-guest-token"] == "test-guest-uuid-1234.1700000000.testsig"
    assert "Bearer test-guest-uuid-1234" in normal_h["Authorization"]

    # Admin command with flag
    admin_h = assistant_cli._headers(admin=True, admin_token="admin-secret-key")
    assert admin_h["Authorization"] == "Bearer admin-secret-key"
    assert "x-guest-token" not in admin_h

    # Admin command without token raises exit 1
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    with pytest.raises(Exception):
        assistant_cli._headers(admin=True, admin_token=None)


def test_cli_config_view():
    """Verify `compass config` displays configuration info with masked token."""
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Compass CLI Configuration" in result.stdout
    assert "API URL" in result.stdout
    assert "[CONFIGURED]" in result.stdout


def test_cli_config_update():
    """Verify `compass config --url ...` updates API base URL."""
    result = runner.invoke(app, ["config", "--url", "http://127.0.0.1:8000"])
    assert result.exit_code == 0
    assert "Configuration saved" in result.stdout
    assert "http://127.0.0.1:8000" in result.stdout


def test_cli_status():
    """Verify `compass status` renders the cross-domain dashboard."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Cognitive Memory Overview" in result.stdout
    assert "HACKATHON" in result.stdout
    assert "COURSEWORK" in result.stdout


def test_cli_projects():
    """Verify `compass projects` lists projects grouped by domain."""
    result = runner.invoke(app, ["projects"])
    assert result.exit_code == 0
    assert "Compass Projects" in result.stdout
    assert any(domain in result.stdout for domain in ("COURSEWORK", "HACKATHON", "CODE"))


def test_cli_tasks_filtered():
    """Verify `compass tasks --domain hackathon --status open` applies filters."""
    result = runner.invoke(app, ["tasks", "--domain", "hackathon", "--status", "open"])
    assert result.exit_code == 0
    assert "Compass Tasks" in result.stdout


def test_cli_add_task():
    """Verify `compass add` creates a new task."""
    result = runner.invoke(app, ["add", "New CLI Test Task", "--domain", "code"])
    assert result.exit_code == 0
    assert "Task created successfully" in result.stdout
    assert "New CLI Test Task" in result.stdout


def test_cli_log_domains():
    """Verify `compass log` logs memory across code and coursework domains."""
    res_code = runner.invoke(app, ["log", "Test code memory via CLI", "--domain", "code", "--tags", "test"])
    assert res_code.exit_code == 0
    assert "Memory logged" in res_code.stdout
    assert "code" in res_code.stdout

    res_cw = runner.invoke(app, ["log", "Test coursework memory via CLI", "--domain", "coursework", "--tags", "test"])
    assert res_cw.exit_code == 0
    assert "Memory logged" in res_cw.stdout
    assert "coursework" in res_cw.stdout


def test_cli_chat_repl():
    """Verify interactive REPL processes two turns and exits cleanly."""
    chat_input = "add a task: CLI REPL verification task, domain hackathon\nwhen is it due?\nexit\n"
    result = runner.invoke(app, ["chat"], input=chat_input)
    assert result.exit_code == 0
    assert "Compass Chat" in result.stdout
    assert "Added task" in result.stdout
    assert "Goodbye!" in result.stdout


def test_cli_triage(monkeypatch):
    """Verify `compass triage` command streams feasibility events and renders markdown."""
    events = [
        {"type": "think", "content": "Analyzing capacity", "metadata": {"agent": "planner"}},
        {"type": "verdict", "content": "REALIST: INFEASIBLE", "metadata": {"agent": "realist"}},
        {"type": "done", "content": "Done", "metadata": {"artifact_markdown": "# Feasibility Triage Artifact\n- Task 1"}},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    mock_resp = MagicMock()
    mock_resp.iter_lines.return_value = lines
    mock_resp.raise_for_status = MagicMock()

    class MockStreamContext:
        def __enter__(self):
            return mock_resp
        def __exit__(self, *args):
            pass

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: MockStreamContext())

    result = runner.invoke(app, ["triage", "--days", "5", "--hours", "4.0"])
    assert result.exit_code == 0
    assert "Starting feasibility negotiation" in result.stdout
    assert "THINK" in result.stdout
    assert "VERDICT" in result.stdout
    assert "Feasibility Triage Artifact" in result.stdout


def test_cli_admin_usage(monkeypatch):
    """Verify `compass admin usage` requires token and displays table."""
    # Fails without token
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    res_fail = runner.invoke(app, ["admin", "usage"])
    assert res_fail.exit_code != 0

    # Succeeds with token
    res_ok = runner.invoke(app, ["admin", "usage", "--token", "test-admin-token"])
    assert res_ok.exit_code == 0
    assert "Token Usage" in res_ok.stdout


def test_cli_admin_undo():
    """Verify `compass agent-undo` calls undo endpoint."""
    result = runner.invoke(app, ["agent-undo", "--run-id", "run_123"])
    assert result.exit_code == 0
    assert "Successfully reverted last mutation" in result.stdout


def test_cli_ctrl_c_exits_130(monkeypatch):
    """Verify Ctrl+C in chat raises exit code 130 without traceback."""
    from cli import assistant_cli

    def mock_stream_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(assistant_cli, "_stream_chat", mock_stream_interrupt)
    result = runner.invoke(app, ["ask", "what is my schedule?"])
    assert result.exit_code == 130
    assert "Traceback" not in result.stderr


def test_cli_backend_integration_tenant_isolation(tmp_path, monkeypatch):
    """Integration test verifying task creation and isolation between Guest A and Guest B against local backend."""
    from cli import assistant_cli

    # Verify local backend is running
    try:
        health = httpx.get("http://127.0.0.1:8000/health", timeout=3.0)
        if health.status_code != 200:
            pytest.skip("Local backend at http://127.0.0.1:8000 is not reachable")
    except Exception:
        pytest.skip("Local backend at http://127.0.0.1:8000 is not reachable")

    # Disable mock network for this integration test
    monkeypatch.undo()

    # 1. Login as Guest A
    dir_a = tmp_path / "guest_a"
    dir_a.mkdir()
    monkeypatch.setattr(assistant_cli, "CONFIG_DIR", dir_a)
    monkeypatch.setattr(assistant_cli, "CONFIG_FILE", dir_a / "config.toml")
    monkeypatch.setattr(assistant_cli, "CREDENTIALS_FILE", dir_a / "credentials.json")
    monkeypatch.setattr(assistant_cli, "API_BASE", "http://127.0.0.1:8000")

    res_login_a = runner.invoke(app, ["login"])
    assert res_login_a.exit_code == 0
    creds_a = assistant_cli.load_credentials()
    assert "guest_id" in creds_a
    gid_a = creds_a["guest_id"]

    # 2. Add task as Guest A
    res_add = runner.invoke(app, ["add", "CLI Isolation Test Task", "--domain", "code"])
    assert res_add.exit_code == 0
    assert "Task created successfully" in res_add.stdout

    # 3. List tasks as Guest A -> task appears
    res_tasks_a = runner.invoke(app, ["tasks"])
    assert res_tasks_a.exit_code == 0
    assert "CLI Isolation" in res_tasks_a.stdout

    # 4. Login as Guest B with existing token in separate dir
    from backend.dependencies import generate_guest_token
    _, gtok_b = generate_guest_token()

    dir_b = tmp_path / "guest_b"
    dir_b.mkdir()
    monkeypatch.setattr(assistant_cli, "CONFIG_DIR", dir_b)
    monkeypatch.setattr(assistant_cli, "CONFIG_FILE", dir_b / "config.toml")
    monkeypatch.setattr(assistant_cli, "CREDENTIALS_FILE", dir_b / "credentials.json")

    res_login_b = runner.invoke(app, ["login", "--token", gtok_b])
    assert res_login_b.exit_code == 0
    creds_b = assistant_cli.load_credentials()
    assert creds_b.get("session_token") == gtok_b

    # 5. List tasks as Guest B -> Guest A task does NOT appear!
    res_tasks_b = runner.invoke(app, ["tasks"])
    assert res_tasks_b.exit_code == 0
    assert "CLI Isolation" not in res_tasks_b.stdout


def test_cli_http_429_retry_after(monkeypatch):
    """Verify 429 response outputs Retry-After on stderr and exits code 1."""
    from cli import assistant_cli

    mock_resp = httpx.Response(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"detail": "Too many requests. Please wait."},
        request=httpx.Request("GET", "http://localhost:8000/api/tasks"),
    )
    err = httpx.HTTPStatusError("429 Too Many Requests", request=mock_resp.request, response=mock_resp)

    def mock_get_err(*args, **kwargs):
        assistant_cli._handle_http_error(err)

    monkeypatch.setattr(assistant_cli, "_get", mock_get_err)
    result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 1
    assert "429" in result.stderr
    assert "Retry-After: 45s" in result.stderr



def test_cli_log_sends_tags_as_a_list_the_backend_accepts(monkeypatch):
    """`compass log --tags a,b` must send a list: the backend model rejects a comma-separated string."""
    from backend.models import LogMemoryRequest
    from cli import assistant_cli

    captured = {}

    def fake_post(path: str, data: dict, headers=None) -> dict:
        captured["path"] = path
        captured["payload"] = data
        return {"status": "ok"}

    monkeypatch.setattr(assistant_cli, "_post", fake_post)
    result = runner.invoke(app, ["log", "Remember the schema", "--domain", "code", "--tags", "test, contract,"])

    assert result.exit_code == 0
    assert captured["payload"]["tags"] == ["test", "contract"]
    # the exact payload must validate against the real request model
    assert LogMemoryRequest(**captured["payload"]).content == "Remember the schema"


def test_cli_log_without_tags_sends_an_empty_list(monkeypatch):
    from cli import assistant_cli

    captured = {}
    monkeypatch.setattr(assistant_cli, "_post", lambda path, data, headers=None: captured.update(data) or {"status": "ok"})
    result = runner.invoke(app, ["log", "No tags here"])

    assert result.exit_code == 0
    assert captured["tags"] == []
