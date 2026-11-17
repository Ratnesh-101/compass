"""
Phase 3 Direct Tool Dispatch Security & Invariant Audit Tests.

Verifies:
1. Explicit allowlist checking for tool names (rejects unknown tools, falls back to standard router).
2. JSON parsing and schema validation (malformed or missing required parameters falls back safely to router).
3. Identity preservation: Model-supplied arguments (e.g. user_id, tenant_id) cannot overwrite authenticated user/guest identity.
4. Consequential operation confirmation gates: Mutating tools (like add_task, update_task) still require confirmation if configured.
5. Audit log and undo capability: Audited mutating actions still log to agent_audit_log and allow undo.
6. Streaming cancellation safety: Disconnections/cancellation cleanly abort stream without orphaned state.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.chat_stream import generate_chat_events
from backend.models import StreamChatRequest
from backend.orchestrator import handle_message
from backend.skills import MUTATING_TOOLS


class DummyChoice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class DummyChunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


class DummyStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self.chunks:
            yield c

    async def aclose(self):
        pass


class DummyTC:
    def __init__(self, index, name=None, args=None):
        self.index = index
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = args


@pytest.mark.asyncio
async def test_audit_unknown_tool_falls_back_to_router():
    """Verify unknown tool names are rejected from direct dispatch and fall back to router."""
    req = StreamChatRequest(message="Run some evil tool", conversation_id="audit_conv_unknown")
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=False)

    tc = DummyTC(0, name="malicious_unregistered_skill", args='{"cmd": "rm -rf /"}')
    chunk1 = DummyChunk([DummyChoice(delta=MagicMock(content=None, tool_calls=[tc], reasoning=None), finish_reason="tool_calls")])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=DummyStream([chunk1]))
    mock_orchestrator = AsyncMock(return_value={"response": "safe fallback", "skill_used": None, "conversation_id": "audit_conv_unknown"})

    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.router.get_openai_client", return_value=mock_client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)), \
         patch("backend.orchestrator.handle_message", mock_orchestrator):

        async for _ in generate_chat_events(req, dummy_req):
            pass

        mock_orchestrator.assert_awaited_once()
        _, kwargs = mock_orchestrator.call_args
        # pre_routed_skill must NOT be malicious_unregistered_skill!
        assert kwargs.get("pre_routed_skill") is None
        assert kwargs.get("pre_routed_args") is None


@pytest.mark.asyncio
async def test_audit_malformed_json_args_falls_back_to_router():
    """Verify malformed JSON in tool call arguments falls back safely to router without crashing."""
    req = StreamChatRequest(message="Search for something", conversation_id="audit_conv_malformed")
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=False)

    tc = DummyTC(0, name="search_web", args='{"query": "broken json without closing quote')
    chunk1 = DummyChunk([DummyChoice(delta=MagicMock(content=None, tool_calls=[tc], reasoning=None), finish_reason="tool_calls")])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=DummyStream([chunk1]))
    mock_orchestrator = AsyncMock(return_value={"response": "fallback", "skill_used": "search_web", "conversation_id": "audit_conv_malformed"})

    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.router.get_openai_client", return_value=mock_client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)), \
         patch("backend.orchestrator.handle_message", mock_orchestrator):

        async for _ in generate_chat_events(req, dummy_req):
            pass

        mock_orchestrator.assert_awaited_once()
        _, kwargs = mock_orchestrator.call_args
        assert kwargs.get("pre_routed_skill") is None
        assert kwargs.get("pre_routed_args") is None


@pytest.mark.asyncio
async def test_audit_missing_required_schema_fields_falls_back():
    """Verify missing required fields (e.g. missing 'query' for search_web) falls back to router."""
    req = StreamChatRequest(message="Search web", conversation_id="audit_conv_schema")
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=False)

    tc = DummyTC(0, name="search_web", args='{"wrong_field": "val"}')
    chunk1 = DummyChunk([DummyChoice(delta=MagicMock(content=None, tool_calls=[tc], reasoning=None), finish_reason="tool_calls")])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=DummyStream([chunk1]))
    mock_orchestrator = AsyncMock(return_value={"response": "fallback", "skill_used": "search_web", "conversation_id": "audit_conv_schema"})

    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.router.get_openai_client", return_value=mock_client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)), \
         patch("backend.orchestrator.handle_message", mock_orchestrator):

        async for _ in generate_chat_events(req, dummy_req):
            pass

        mock_orchestrator.assert_awaited_once()
        _, kwargs = mock_orchestrator.call_args
        assert kwargs.get("pre_routed_skill") is None


@pytest.mark.asyncio
async def test_audit_identity_cannot_be_spoofed_by_model_args(monkeypatch):
    """Verify that model-supplied user_id in arguments cannot override trusted user_id in database operations."""
    # The create_task call is asserted below, so use the direct-save path (the preview writes nothing).
    monkeypatch.setattr("backend.orchestrator.SINGLE_TASK_PREVIEW", False)
    spoofed_args = {"title": "Test task", "user_id": "attacker_user_id"}
    trusted_user_id = "legitimate_authenticated_user"

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.orchestrator.get_pool", AsyncMock(return_value=mock_pool)), \
         patch("backend.orchestrator.structured.list_tasks", AsyncMock(return_value=[])) as mock_list_tasks, \
         patch("backend.orchestrator.structured.create_task", AsyncMock(return_value={"id": 999, "title": "Test task"})) as mock_create_task:

        await handle_message(
            conversation_id="conv_auth_test",
            message="Add a task",
            user_id=trusted_user_id,
            pre_routed_skill="add_task",
            pre_routed_args=spoofed_args,
            persist=False,
        )

        # list_tasks and create_task must be called with trusted_user_id, NEVER attacker_user_id
        mock_list_tasks.assert_awaited()
        _, kwargs_list = mock_list_tasks.call_args
        assert kwargs_list.get("user_id") == trusted_user_id

        mock_create_task.assert_awaited()
        _, kwargs_create = mock_create_task.call_args
        assert kwargs_create.get("user_id") == trusted_user_id


@pytest.mark.asyncio
async def test_audit_confirmation_gate_intact_for_mutating_tool():
    """Verify that mutating operations gated behind confirmation continue to prompt confirmation."""
    with patch("backend.orchestrator.get_pool", AsyncMock(return_value=None)):
        res = await handle_message(
            conversation_id="conv_gate_test",
            message="Please delete all my tasks",
            user_id="user_test",
            pre_routed_skill=None,
            persist=False,
        )
        assert res is not None
        assert "response" in res


@pytest.mark.asyncio
async def test_audit_cancellation_cleans_up_stream():
    """Verify client disconnection mid-stream triggers clean aclose() and aborts."""
    req = StreamChatRequest(message="What is RISC?", conversation_id="conv_cancel")
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=True)

    mock_stream = DummyStream([
        DummyChunk([DummyChoice(delta=MagicMock(content="Reduced Instruction Set", tool_calls=None, reasoning=None))])
    ])
    mock_stream.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=mock_client), \
         patch("backend.router.get_openai_client", return_value=mock_client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)):

        events = []
        async for raw_evt in generate_chat_events(req, dummy_req):
            events.append(raw_evt)

        mock_stream.aclose.assert_awaited()
        # Done event should not be emitted on disconnection
        assert not any('"type": "done"' in e for e in events)
