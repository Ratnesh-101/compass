"""Reject / approve request-shape tests for cli.cli_agent_runner.run_interactive_agent_session.

No database, no network: httpx.stream / httpx.post and rich's Prompt.ask are faked.
"""
import json
from contextlib import contextmanager

from backend.models import AgentConfirmRequest, AgentRequest
from cli import cli_agent_runner
from cli.cli_agent_runner import run_interactive_agent_session

API_BASE = "http://test.invalid"
GOAL = "Plan my week"
RUN_ID = "run-123"


def _sse(*events):
    return "".join(f"data: {json.dumps(ev)}\n" for ev in events)


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body

    def raise_for_status(self):
        return None

    def iter_text(self):
        yield self._body


class _Recorder:
    """Fake httpx.stream: returns scripted SSE bodies in order and records each json body."""

    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.json_bodies = []

    def __call__(self, method, url, **kwargs):
        self.json_bodies.append(kwargs.get("json"))
        body = self._bodies.pop(0) if self._bodies else ""

        @contextmanager
        def cm():
            yield _FakeResponse(body)

        return cm()


class _FakePostResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"results": []}


def _confirm_events(with_run_id: bool):
    events = []
    if with_run_id:
        events.append({"type": "think", "run_id": RUN_ID, "content": ""})
    events.append({
        "type": "confirm_request",
        "tool": "update_task",
        "args": {"task_id": 7},
        "content": "Move the OS Homework 2 deadline?",
    })
    return _sse(*events)


def test_reject_request_body_is_valid_agent_request(monkeypatch):
    recorder = _Recorder([_confirm_events(with_run_id=True), _sse({"type": "done", "content": ""})])
    monkeypatch.setattr(cli_agent_runner.httpx, "stream", recorder)

    run_interactive_agent_session(API_BASE, goal=GOAL, demo_reject=True)

    assert len(recorder.json_bodies) == 2
    body = recorder.json_bodies[1]
    AgentRequest(**body)  # raises if the body does not match the backend model
    assert body["action"] == "reject"
    assert body["run_id"] == RUN_ID
    assert body["goal"] == GOAL


def test_approve_posts_confirm_with_run_id(monkeypatch):
    recorder = _Recorder([_confirm_events(with_run_id=True)])
    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return _FakePostResponse()

    monkeypatch.setattr(cli_agent_runner.httpx, "stream", recorder)
    monkeypatch.setattr(cli_agent_runner.httpx, "post", fake_post)
    monkeypatch.setattr(cli_agent_runner.Prompt, "ask", lambda *a, **k: "yes")

    run_interactive_agent_session(API_BASE, goal=GOAL)

    assert len(posts) == 1
    url, body = posts[0]
    assert url.endswith("/api/agent/confirm")
    AgentConfirmRequest(**body)  # raises if the body does not match the backend model
    assert body["run_id"] == RUN_ID


def test_approve_without_run_id_does_not_post(monkeypatch):
    recorder = _Recorder([_confirm_events(with_run_id=False)])
    posts = []
    monkeypatch.setattr(cli_agent_runner.httpx, "stream", recorder)
    monkeypatch.setattr(cli_agent_runner.httpx, "post", lambda url, **kw: posts.append(url))
    monkeypatch.setattr(cli_agent_runner.Prompt, "ask", lambda *a, **k: "yes")

    run_interactive_agent_session(API_BASE, goal=GOAL)

    assert posts == []
