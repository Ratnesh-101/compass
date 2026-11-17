"""Unit tests for backend/services/stream_watch.py and its call sites (no database, fakes only).

Covers: bounded / slow pool acquire, the silent-stream watchdog, start/end log lines, and the
post-commit bound so a saved change still gets its reply and done event.
"""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import StreamChatRequest
from backend.services import chat_idempotency, chat_stream, stream_watch
from backend.services.chat_stream_extras import orchestrate_with_early_commit
from backend.services.stream_watch import PoolAcquireTimeout, StreamTrace, timed_acquire


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, delay=0.0, hang=False):
        self.delay, self.hang, self.exits = delay, hang, []

    async def __aenter__(self):
        if self.hang:
            await asyncio.Event().wait()  # never returns: a drained pool
        if self.delay:
            await asyncio.sleep(self.delay)
        return "conn"

    async def __aexit__(self, *exc):
        self.exits.append(exc)
        return False


class _Pool:
    def __init__(self, **kw):
        self.kw, self.ctxs = kw, []

    def acquire(self):
        ctx = _Ctx(**self.kw)
        self.ctxs.append(ctx)
        return ctx


def _request(disconnected=False):
    return SimpleNamespace(is_disconnected=AsyncMock(return_value=disconnected))


def _status(stage):
    return f'data: {json.dumps({"type": "status", "stage": stage, "label": "x"})}\n\n'


DONE = 'data: {"type": "done", "conversation_id": "conv-1"}\n\n'
ERROR = 'data: {"type": "error", "detail": "boom", "terminal": true}\n\n'


def _lines(caplog, needle):
    return [r.getMessage() for r in caplog.records if needle in r.getMessage()]


# ---------------------------------------------------------------------------
# timed_acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fast_acquire_returns_connection_without_warning(caplog):
    caplog.set_level(logging.INFO)
    pool = _Pool()
    async with timed_acquire(pool, "rid-1", "fast") as conn:
        assert conn == "conn"
    assert pool.ctxs[0].exits == [(None, None, None)]
    assert not _lines(caplog, "pool_acquire_")


@pytest.mark.asyncio
async def test_slow_acquire_logs_warning_with_request_id_label_and_wait(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "SLOW_ACQUIRE_WARN_S", 0.01)
    async with timed_acquire(_Pool(delay=0.05), "rid-slow", "post_save") as conn:
        assert conn == "conn"
    msgs = _lines(caplog, "pool_acquire_slow")
    assert len(msgs) == 1
    assert "request_id=rid-slow" in msgs[0] and "label=post_save" in msgs[0] and "waited_s=" in msgs[0]
    rec = [r for r in caplog.records if "pool_acquire_slow" in r.getMessage()][0]
    assert rec.levelno == logging.WARNING


@pytest.mark.asyncio
async def test_drained_pool_times_out_with_logged_error_instead_of_hanging(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "POOL_ACQUIRE_TIMEOUT_S", 0.05)
    with pytest.raises(PoolAcquireTimeout):
        async with timed_acquire(_Pool(hang=True), "rid-drained", "persist"):
            pytest.fail("body must not run")
    msgs = _lines(caplog, "pool_acquire_timeout")
    assert len(msgs) == 1
    assert "request_id=rid-drained" in msgs[0] and "label=persist" in msgs[0] and "limit_s=" in msgs[0]


@pytest.mark.asyncio
async def test_explicit_timeout_argument_overrides_the_default(monkeypatch):
    monkeypatch.setattr(stream_watch, "POOL_ACQUIRE_TIMEOUT_S", 60.0)
    with pytest.raises(PoolAcquireTimeout):
        async with timed_acquire(_Pool(hang=True), "r", "x", timeout=0.02):
            pass


@pytest.mark.asyncio
async def test_body_exception_releases_the_connection_and_propagates():
    pool = _Pool()
    with pytest.raises(ValueError):
        async with timed_acquire(pool, "r", "x"):
            raise ValueError("body failed")
    assert pool.ctxs[0].exits and pool.ctxs[0].exits[0][0] is ValueError


@pytest.mark.asyncio
async def test_persist_stream_messages_returns_false_and_logs_when_pool_is_drained(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "POOL_ACQUIRE_TIMEOUT_S", 0.05)
    with patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=_Pool(hang=True))):
        ok = await asyncio.wait_for(
            chat_stream.persist_stream_messages("conv-x", "q", "answer", user_id="u", request_id="rid-persist"), 2
        )
    assert ok is False
    assert any("label=persist_stream_messages" in m and "request_id=rid-persist" in m
               for m in _lines(caplog, "pool_acquire_timeout"))


@pytest.mark.asyncio
async def test_idempotency_finish_gives_up_on_a_drained_pool_without_raising(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "POOL_ACQUIRE_TIMEOUT_S", 0.05)
    await asyncio.wait_for(
        chat_idempotency._finish(_Pool(hang=True), "owner", "rid-finish", {"success": True, "skill_used": "add_task"}), 2
    )
    assert any("label=idempotency_finish" in m and "request_id=rid-finish" in m
               for m in _lines(caplog, "pool_acquire_timeout"))
    assert _lines(caplog, "Could not finalize chat request rid-finish")


# ---------------------------------------------------------------------------
# StreamTrace: start/end lines and the watchdog
# ---------------------------------------------------------------------------

async def _run(trace, source, request=None):
    return [f async for f in trace.run(source, request or _request())]


@pytest.mark.asyncio
async def test_start_and_end_lines_report_stage_elapsed_and_done(caplog):
    caplog.set_level(logging.INFO)

    async def source():
        yield ": ping\n\n"
        yield _status("thinking")
        yield DONE

    trace = StreamTrace("rid-ok", "conv-1")
    frames = await _run(trace, source())
    assert len(frames) == 3
    assert _lines(caplog, "chat_stream_start request_id=rid-ok conversation_id=conv-1")
    end = _lines(caplog, "chat_stream_end")
    assert len(end) == 1
    assert "request_id=rid-ok" in end[0] and "stage=done" in end[0]
    assert "elapsed_s=" in end[0] and "outcome=done" in end[0]


@pytest.mark.asyncio
async def test_end_line_reports_error_outcome(caplog):
    caplog.set_level(logging.INFO)

    async def source():
        yield ERROR

    await _run(StreamTrace("rid-err", "c"), source())
    assert "outcome=error" in _lines(caplog, "chat_stream_end")[0]


@pytest.mark.asyncio
async def test_end_line_reports_disconnect_when_the_generator_is_closed_early(caplog):
    caplog.set_level(logging.INFO)

    async def source():
        yield _status("generating")
        await asyncio.sleep(10)
        yield DONE

    gen = StreamTrace("rid-dc", "c").run(source(), _request())
    assert await gen.__anext__() == _status("generating")
    await gen.aclose()
    end = _lines(caplog, "chat_stream_end")
    assert len(end) == 1 and "outcome=disconnect" in end[0] and "stage=status:generating" in end[0]


@pytest.mark.asyncio
async def test_end_line_reports_exception_outcome_and_reraises(caplog):
    caplog.set_level(logging.INFO)

    async def source():
        yield _status("thinking")
        raise RuntimeError("inner failure")

    with pytest.raises(RuntimeError):
        await _run(StreamTrace("rid-exc", "c"), source())
    assert "outcome=exception" in _lines(caplog, "chat_stream_end")[0]


@pytest.mark.asyncio
async def test_watchdog_fires_once_and_keepalives_do_not_reset_it(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "WATCHDOG_SILENCE_S", 0.15)

    async def source():
        yield _status("thinking")
        for _ in range(5):
            await asyncio.sleep(0.1)
            yield ": ping\n\n"
        yield DONE

    await _run(StreamTrace("rid-silent", "conv-9"), source())
    msgs = _lines(caplog, "chat_stream_silent")
    assert len(msgs) == 1
    assert "request_id=rid-silent" in msgs[0] and "conversation_id=conv-9" in msgs[0]
    assert "last_stage=status:thinking" in msgs[0] and "silent_for_s=" in msgs[0]
    rec = [r for r in caplog.records if "chat_stream_silent" in r.getMessage()][0]
    assert rec.levelno == logging.WARNING


@pytest.mark.asyncio
async def test_watchdog_stays_quiet_when_events_keep_flowing(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "WATCHDOG_SILENCE_S", 0.2)

    async def source():
        for _ in range(6):
            await asyncio.sleep(0.05)
            yield 'data: {"type": "token", "value": "a"}\n\n'
        yield DONE

    await _run(StreamTrace("rid-busy", "c"), source())
    assert not _lines(caplog, "chat_stream_silent")


@pytest.mark.asyncio
async def test_watchdog_stops_when_the_stream_ends(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "WATCHDOG_SILENCE_S", 0.1)

    async def source():
        yield DONE

    trace = StreamTrace("rid-end", "c")
    await _run(trace, source())
    await asyncio.sleep(0.3)
    assert trace._watch_task.done()
    assert not _lines(caplog, "chat_stream_silent")


@pytest.mark.asyncio
async def test_watchdog_does_not_warn_after_client_disconnect(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "WATCHDOG_SILENCE_S", 0.05)

    async def source():
        yield _status("thinking")
        await asyncio.sleep(0.3)
        yield DONE

    await _run(StreamTrace("rid-gone", "c"), source(), _request(disconnected=True))
    assert not _lines(caplog, "chat_stream_silent")


@pytest.mark.asyncio
async def test_watchdog_never_raises_when_the_request_object_is_broken(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "WATCHDOG_SILENCE_S", 0.05)

    async def source():
        yield _status("thinking")
        await asyncio.sleep(0.2)
        yield DONE

    frames = await _run(StreamTrace("rid-bad-req", "c"), source(), request=object())
    assert frames[-1] == DONE


def test_classify_frame_ignores_keepalives_and_names_stages():
    assert stream_watch.classify_frame(": ping\n\n") is None
    assert stream_watch.classify_frame('data: {"type": "ping"}\n\n') is None
    assert stream_watch.classify_frame(_status("searching")) == "status:searching"
    assert stream_watch.classify_frame('data: {"type": "committed", "count": 1}\n\n') == "committed"
    assert stream_watch.classify_frame(DONE) == "done"


# ---------------------------------------------------------------------------
# Post-commit bound
# ---------------------------------------------------------------------------

def _commit():
    chat_idempotency.record_committed_outcome({"id": 5, "title": "Write tests"}, conv_id="conv-1")


@pytest.mark.asyncio
async def test_orchestrator_hang_after_commit_still_returns_a_result(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "POST_COMMIT_TIMEOUT_S", 0.1)
    release = asyncio.Event()

    async def fake_handle(**kwargs):
        _commit()
        await release.wait()  # e.g. a write waiting on a drained pool
        return {"success": True, "skill_used": "add_task", "response": "late"}

    items = await asyncio.wait_for(
        _collect(orchestrate_with_early_commit(fake_handle, trace_id="rid-hang", message="x")), 3
    )
    assert [k for k, _ in items] == ["committed", "result"]
    result = items[1][1]
    assert result["success"] is True and result["skill_used"] == "add_task"
    assert "Write tests" in result["response"] and result["degraded"] == "post_commit_timeout"
    assert any("request_id=rid-hang" in m for m in _lines(caplog, "post_commit_timeout"))
    release.set()
    await asyncio.sleep(0.05)
    assert any("request_id=rid-hang" in m and "outcome=ok" in m for m in _lines(caplog, "post_commit_late_finish"))


@pytest.mark.asyncio
async def test_orchestrator_error_after_commit_yields_the_saved_result(caplog):
    caplog.set_level(logging.INFO)

    async def fake_handle(**kwargs):
        _commit()
        await asyncio.sleep(0.01)
        raise RuntimeError("audit log write failed")

    items = await _collect(orchestrate_with_early_commit(fake_handle, trace_id="rid-err2", message="x"))
    assert [k for k, _ in items] == ["committed", "result"]
    assert items[1][1]["degraded"] == "post_commit_error"
    msgs = _lines(caplog, "post_commit_error")
    assert msgs and "request_id=rid-err2" in msgs[0] and "RuntimeError" in msgs[0]


@pytest.mark.asyncio
async def test_error_before_any_commit_still_propagates():
    async def fake_handle(**kwargs):
        raise RuntimeError("nothing was saved")

    with pytest.raises(RuntimeError):
        await _collect(orchestrate_with_early_commit(fake_handle, message="x"))


@pytest.mark.asyncio
async def test_trace_id_is_not_forwarded_to_the_orchestrator():
    seen = {}

    async def fake_handle(**kwargs):
        seen.update(kwargs)
        return {"success": True, "skill_used": "chat", "response": "hi"}

    await _collect(orchestrate_with_early_commit(fake_handle, trace_id="t", message="x"))
    assert "trace_id" not in seen and seen["message"] == "x"


async def _collect(agen):
    return [item async for item in agen]


@pytest.mark.asyncio
async def test_stream_still_sends_text_and_done_when_the_orchestrator_hangs_after_commit(monkeypatch, caplog):
    """End to end through generate_chat_events with fakes: saved task, hung orchestrator, stream completes."""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stream_watch, "POST_COMMIT_TIMEOUT_S", 0.1)
    release = asyncio.Event()

    async def fake_handle(**kwargs):
        _commit()
        await release.wait()
        return {"success": True, "skill_used": "add_task", "response": "late"}

    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    req = StreamChatRequest(message="undo", request_id="req_12345678")
    with patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)), \
         patch("backend.services.chat_stream._get_stream_client", MagicMock()), \
         patch("backend.services.chat_stream.orchestrator.handle_message", side_effect=fake_handle), \
         patch("backend.services.chat_stream._schedule_stream_persistence", MagicMock()):
        events = await asyncio.wait_for(
            _collect(chat_stream.generate_chat_events(req, request, user_id="u-watch")), 5
        )
    release.set()
    parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
    types = [p["type"] for p in parsed]
    assert "committed" in types and "done" in types
    assert types.index("committed") < types.index("token") < types.index("done")
    assert "Write tests" in "".join(p.get("value", "") for p in parsed if p["type"] == "token")
    assert [p for p in parsed if p["type"] == "done"][0]["skill_used"] == "add_task"
    assert any("request_id=req_12345678" in m for m in _lines(caplog, "post_commit_timeout"))
    assert any("request_id=req_12345678" in m and "outcome=done" in m for m in _lines(caplog, "chat_stream_end"))
