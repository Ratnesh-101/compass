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
    """Verify `compass config --url ... --token ...` updates settings."""
    result = runner.invoke(app, ["config", "--url", "http://127.0.0.1:9000", "--token", "test-token-123"])
    assert result.exit_code == 0
    assert "Configuration saved" in result.stdout
    assert "http://127.0.0.1:9000" in result.stdout
