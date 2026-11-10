"""Regression tests for CLI and tooling fixes.

No database, no network: the backend HTTP helpers, httpx.stream and the
size-check script's file system walk are all faked or avoided.
"""
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from backend.models import CreateTaskRequest
from cli import assistant_cli, cli_agent_runner

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


# 1. assistant_cli `add --project` must send the backend field name "project".

def test_add_sends_project_field_expected_by_backend(monkeypatch):
    captured = {}

    def fake_post(path, data, headers=None):
        captured["path"] = path
        captured["body"] = data
        return {"id": 1, "title": "Write report", "status": "open"}

    monkeypatch.setattr(assistant_cli, "_post", fake_post)

    result = runner.invoke(assistant_cli.app, ["add", "Write report", "--project", "Thesis"])

    assert result.exit_code == 0, result.output
    body = captured["body"]
    assert body["project"] == "Thesis"
    assert "project_id" not in body
    CreateTaskRequest(**body)  # raises if the body does not match the backend model


# 2. run_feasibility_triage_session must survive a malformed SSE data line.

class _StreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield from self._lines


def test_triage_stream_continues_past_malformed_data_line(monkeypatch):
    lines = [
        "data: not-json",
        "data: " + json.dumps(
            {"type": "think", "content": "hello-marker", "metadata": {"agent": "planner"}}
        ),
    ]

    @contextmanager
    def fake_stream(method, url, **kwargs):
        yield _StreamResponse(lines)

    printed = []
    monkeypatch.setattr(cli_agent_runner.httpx, "stream", fake_stream)
    monkeypatch.setattr(
        cli_agent_runner.console,
        "print",
        lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args)),
    )

    cli_agent_runner.run_feasibility_triage_session("http://test.invalid", {}, days=1, hours=1.0)

    assert any("hello-marker" in text for text in printed), printed


# 3. scripts/check_file_sizes.py: virtualenv directories with suffixes are dependencies.

def _load_check_file_sizes():
    spec = importlib.util.spec_from_file_location(
        "check_file_sizes_under_test", REPO_ROOT / "scripts" / "check_file_sizes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # the script has an __main__ guard, so no scan runs
    return module


def test_suffixed_virtualenv_dirs_are_dependencies(tmp_path):
    checker = _load_check_file_sizes()
    root = tmp_path

    assert checker.classify_file(root / ".venv311" / "Lib" / "big.py", root) == "DEPENDENCY"
    assert checker.classify_file(root / "venv-test" / "Lib" / "big.py", root) == "DEPENDENCY"
    assert checker.classify_file(root / ".python-packages" / "pkg" / "big.py", root) == "DEPENDENCY"


def test_source_file_is_not_dependency(tmp_path):
    checker = _load_check_file_sizes()
    root = tmp_path

    assert checker.classify_file(root / "backend" / "main.py", root) != "DEPENDENCY"
    # the prefix rule applies to directories only, never to a file name
    assert checker.classify_file(root / "cli" / "venv_client.py", root) != "DEPENDENCY"


# 4. .gitignore must exclude the local audit report.

def test_gitignore_excludes_security_audit_report():
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "SECURITY_AUDIT_REPORT.md" in lines
