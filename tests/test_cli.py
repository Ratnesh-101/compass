"""
Compass — CLI Command Tests via Typer CliRunner.
"""

from typer.testing import CliRunner
from cli.assistant_cli import app

runner = CliRunner()


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
    result = runner.invoke(app, ["config", "--url", "http://127.0.0.1:8000", "--token", "dev-token"])
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
