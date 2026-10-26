"""
Compass — CLI Command Tests via Typer CliRunner.
"""

import pytest
from typer.testing import CliRunner
from cli.assistant_cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_cli_network(monkeypatch):
    """Hermetically mock CLI HTTP calls so tests do not depend on an external running server."""
    from cli import assistant_cli

    def mock_get(path: str, params: dict | None = None) -> dict:
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
        return {}

    def mock_post(path: str, data: dict) -> dict:
        if "/api/log" in path or "/memory/log" in path:
            return {
                "status": "ok",
                "message": "Memory logged successfully",
                "entry_id": 42,
            }
        elif "/chat" in path:
            return {
                "response": "Added task: CLI REPL verification task\nwhen is it due? It is due on 2026-09-21.",
                "conversation_id": "conv_repl_123",
                "skill_used": "add_task",
            }
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


def test_cli_config_view():
    """Verify `compass config` displays configuration info."""
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Compass CLI Configuration" in result.stdout
    assert "API URL" in result.stdout


def test_cli_config_update():
    """Verify `compass config --url ... --token ...` updates settings and restores valid URL."""
    from cli import assistant_cli
    orig_url = assistant_cli.API_BASE
    orig_token = assistant_cli.AUTH_TOKEN
    try:
        result = runner.invoke(app, ["config", "--url", "http://127.0.0.1:8000", "--token", "dev-token"])
        assert result.exit_code == 0
        assert "Configuration saved" in result.stdout
        assert "http://127.0.0.1:8000" in result.stdout
    finally:
        runner.invoke(app, ["config", "--url", orig_url, "--token", orig_token])


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
    import json
    from unittest.mock import MagicMock

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


def test_cli_log_sends_content_contract(monkeypatch):
    """Regression test: verify `compass log` sends 'content' to satisfy backend contract."""
    from cli import assistant_cli

    captured_payload = {}

    def mock_post_capture(path: str, data: dict) -> dict:
        if "/api/log" in path:
            captured_payload.update(data)
            return {"status": "ok", "message": "Memory logged successfully"}
        return {}

    monkeypatch.setattr(assistant_cli, "_post", mock_post_capture)
    result = runner.invoke(app, ["log", "Test contract payload", "--domain", "code", "--tags", "test,contract"])
    assert result.exit_code == 0
    assert "content" in captured_payload
    assert captured_payload["content"] == "Test contract payload"
    assert captured_payload["summary"] == "Test contract payload"
    assert captured_payload["tags"] == ["test", "contract"]


def test_cli_agent_runner_passes_auth_headers(monkeypatch):
    """Regression test: verify run_interactive_agent_session passes Authorization Bearer token."""
    from cli.cli_agent_runner import run_interactive_agent_session
    from unittest.mock import MagicMock

    called_kwargs = {}

    class MockStreamContext:
        def __init__(self, *args, **kwargs):
            called_kwargs.update(kwargs)
        def __enter__(self):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.iter_text.return_value = ['data: {"type": "done", "content": "{\\"tools_used\\": [], \\"total_steps\\": 1}"}\n']
            return resp
        def __exit__(self, *args):
            pass

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: MockStreamContext(*args, **kwargs))

    run_interactive_agent_session(
        api_base="http://127.0.0.1:8000",
        auth_token="test-secret-token",
        goal="Test goal",
    )

    headers = called_kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer test-secret-token"


def test_cli_agent_inspection_commands_pass_auth_headers(monkeypatch):
    """Regression test: verify agent-activity, agent-stats, agent-runs send auth headers."""
    import httpx
    from unittest.mock import MagicMock

    captured_headers = []

    def mock_httpx_get(url: str, *args, **kwargs):
        headers = kwargs.get("headers", {})
        captured_headers.append((url, headers))
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        if "activity" in url:
            mock_resp.json.return_value = {"activity": []}
        elif "critique-stats" in url:
            mock_resp.json.return_value = {"total_critique_passes": 0}
        elif "runs" in url:
            mock_resp.json.return_value = {"runs": []}
        elif "proactive-briefing" in url:
            mock_resp.json.return_value = {"briefing": "All clear"}
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_httpx_get)

    res1 = runner.invoke(app, ["agent-activity"])
    assert res1.exit_code == 0
    assert any("Authorization" in h and "Bearer" in h["Authorization"] for _, h in captured_headers if "activity" in _)

    res2 = runner.invoke(app, ["agent-stats"])
    assert res2.exit_code == 0
    assert any("Authorization" in h and "Bearer" in h["Authorization"] for _, h in captured_headers if "critique-stats" in _)

    res3 = runner.invoke(app, ["agent-runs"])
    assert res3.exit_code == 0
    assert any("Authorization" in h and "Bearer" in h["Authorization"] for _, h in captured_headers if "runs" in _)

    res4 = runner.invoke(app, ["agent-briefing"])
    assert res4.exit_code == 0
    assert any("Authorization" in h and "Bearer" in h["Authorization"] for _, h in captured_headers if "proactive-briefing" in _)
