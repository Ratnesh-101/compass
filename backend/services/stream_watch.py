"""Compass — chat stream diagnostics and time bounds ("silent stream" follow-up).

A chat stream once saved a task and then went silent until the connection was reset. The cause is not
proven; one theory is a drained database pool with a post-save write waiting for a connection forever.
This module makes that visible and bounded without assuming it:

  * `timed_acquire`   a pool acquire that logs slow waits and gives up after a limit,
  * `StreamTrace`     start/end log lines for every chat stream plus a silent-stream watchdog,
  * post-commit helpers used by `orchestrate_with_early_commit` so a saved change still gets its reply.

Leaf module: it must not import chat_stream, chat_stream_extras or chat_idempotency (they import it).
Log line formats are listed in the docstrings so they can be searched in Render logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger("compass.services.stream_watch")

# Module constants, read at call time so tests (and operators via code) can adjust them.
POOL_ACQUIRE_TIMEOUT_S = 10.0   # give up waiting for a pooled connection after this long
SLOW_ACQUIRE_WARN_S = 1.0       # log a WARNING when a connection took longer than this
POST_COMMIT_TIMEOUT_S = 25.0    # after a change is saved, wait at most this long for the orchestrator to return
WATCHDOG_SILENCE_S = 20.0       # warn when no non-keepalive event was emitted for this long


class PoolAcquireTimeout(TimeoutError):
    """No pooled database connection became available within the allowed time."""


@contextlib.asynccontextmanager
async def timed_acquire(
    pool: Any, request_id: Optional[str], label: str, timeout: Optional[float] = None
) -> AsyncIterator[Any]:
    """`async with timed_acquire(pool, rid, "label") as conn:` instead of `async with pool.acquire() as conn:`.

    Logs, searchable in Render logs:
      WARNING pool_acquire_slow request_id=<id> label=<label> waited_s=<n.n>
      ERROR   pool_acquire_timeout request_id=<id> label=<label> waited_s=<n.n> limit_s=<n.n>
    A timeout raises PoolAcquireTimeout (a TimeoutError) instead of waiting forever.
    """
    limit = POOL_ACQUIRE_TIMEOUT_S if timeout is None else timeout
    rid = request_id or "-"
    cm = pool.acquire()
    started = time.perf_counter()
    try:
        conn = await asyncio.wait_for(cm.__aenter__(), limit)
    except asyncio.TimeoutError:
        waited = time.perf_counter() - started
        logger.error(
            "pool_acquire_timeout request_id=%s label=%s waited_s=%.1f limit_s=%.1f", rid, label, waited, limit
        )
        raise PoolAcquireTimeout(f"no database connection for '{label}' within {limit:.1f}s") from None
    waited = time.perf_counter() - started
    if waited > SLOW_ACQUIRE_WARN_S:
        logger.warning("pool_acquire_slow request_id=%s label=%s waited_s=%.1f", rid, label, waited)
    try:
        yield conn
    except BaseException as exc:
        await cm.__aexit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        await cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Post-commit bounds (used by chat_stream_extras.orchestrate_with_early_commit)
# ---------------------------------------------------------------------------

def degraded_result(committed: Optional[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    """A reply built from the "committed" payload, used when the orchestrator did not return in time
    (or raised) after the change was already saved. Keeps the saved result visible to the user."""
    result: Dict[str, Any] = dict(committed or {})
    result["success"] = True
    result.setdefault("skill_used", "add_task")
    result["response"] = result.get("response") or result.get("message") or "Done. Your change was saved."
    result["degraded"] = reason
    return result


def late_outcome_logger(request_id: str) -> Any:
    """Done-callback for the orchestrator task we stopped waiting for. Also retrieves its exception.

    Logs: WARNING post_commit_late_finish request_id=<id> outcome=<ok|cancelled|error:<Type>>"""

    def _callback(task: "asyncio.Future[Any]") -> None:
        try:
            if task.cancelled():
                outcome = "cancelled"
            elif task.exception() is not None:
                outcome = f"error:{type(task.exception()).__name__}"
            else:
                outcome = "ok"
            logger.warning("post_commit_late_finish request_id=%s outcome=%s", request_id, outcome)
        except Exception:  # a logging callback must never raise
            pass

    return _callback


# ---------------------------------------------------------------------------
# Per-stream trace: start/end lines and the silent-stream watchdog
# ---------------------------------------------------------------------------

_TYPE_RE = re.compile(r'"type":\s*"([A-Za-z_]+)"')
_STAGE_RE = re.compile(r'"stage":\s*"([A-Za-z_]+)"')


def classify_frame(frame: str) -> Optional[str]:
    """Stage label for an SSE frame, or None for keepalives (comments and `ping` events)."""
    if not isinstance(frame, str) or not frame.startswith("data:"):
        return None
    m = _TYPE_RE.search(frame[:80])
    kind = m.group(1) if m else "event"
    if kind == "ping":
        return None
    if kind == "status":
        s = _STAGE_RE.search(frame[:200])
        return f"status:{s.group(1)}" if s else "status"
    return kind


async def _aclose_quietly(source: Any) -> None:
    closer = getattr(source, "aclose", None)
    if closer is not None:
        with contextlib.suppress(Exception):
            await closer()


class StreamTrace:
    """Tracks one chat stream. Logs, searchable in Render logs:

      INFO    chat_stream_start request_id=<id> conversation_id=<id>
      INFO    chat_stream_end   request_id=<id> conversation_id=<id> stage=<last stage> elapsed_s=<n.n> outcome=<o>
              outcome is one of: done, error, disconnect, exception, ended_without_terminal
      WARNING chat_stream_silent request_id=<id> conversation_id=<id> last_stage=<stage> silent_for_s=<n.n>
              (once per stream, when no event other than a keepalive was emitted for WATCHDOG_SILENCE_S)

    A stream that logged chat_stream_start but never chat_stream_end is still running or was killed with the process."""

    def __init__(self, request_id: Optional[str], conversation_id: Optional[str]) -> None:
        self.request_id = request_id or f"anon-{uuid.uuid4().hex[:8]}"
        self.conversation_id = conversation_id or "-"
        self.stage = "start"
        self.terminal: Optional[str] = None
        self.warned = False
        self.started = self.last_event = time.monotonic()
        self._watch_task: Optional["asyncio.Future[None]"] = None

    def note(self, frame: str) -> None:
        """Record an emitted frame. Never raises."""
        try:
            label = classify_frame(frame)
            if label is None:
                return
            self.stage = label
            self.last_event = time.monotonic()
            if label == "done":
                self.terminal = "done"
                with contextlib.suppress(Exception):
                    cid = json.loads(frame[5:].strip()).get("conversation_id")
                    if cid:
                        self.conversation_id = str(cid)
            elif label == "error":
                self.terminal = "error"
        except Exception:
            pass

    async def _client_gone(self, request: Any) -> bool:
        try:
            return bool(await request.is_disconnected())
        except Exception:
            return False

    async def _watch(self, request: Any) -> None:
        try:
            while True:
                remaining = WATCHDOG_SILENCE_S - (time.monotonic() - self.last_event)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    continue
                if await self._client_gone(request):
                    return
                self.warned = True
                logger.warning(
                    "chat_stream_silent request_id=%s conversation_id=%s last_stage=%s silent_for_s=%.1f",
                    self.request_id, self.conversation_id, self.stage, time.monotonic() - self.last_event,
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # the watchdog must never break a stream
            logger.debug("stream watchdog stopped: %s", e)

    def _stop_watch(self) -> None:
        task = self._watch_task
        if task is not None and not task.done():
            task.cancel()

    def _log_end(self, outcome: str) -> None:
        try:
            logger.info(
                "chat_stream_end request_id=%s conversation_id=%s stage=%s elapsed_s=%.1f outcome=%s",
                self.request_id, self.conversation_id, self.stage, time.monotonic() - self.started, outcome,
            )
        except Exception:
            pass

    async def run(self, source: AsyncIterator[str], request: Any) -> AsyncIterator[str]:
        """Pass frames through from `source`, logging start/end and running the watchdog."""
        logger.info("chat_stream_start request_id=%s conversation_id=%s", self.request_id, self.conversation_id)
        outcome = "ended_without_terminal"
        self._watch_task = asyncio.ensure_future(self._watch(request))
        try:
            async for frame in source:
                self.note(frame)
                yield frame
            outcome = self.terminal or "ended_without_terminal"
        except (asyncio.CancelledError, GeneratorExit):
            outcome = self.terminal or "disconnect"
            raise
        except Exception:
            outcome = "exception"
            raise
        finally:
            self._stop_watch()
            self._log_end(outcome)
            await _aclose_quietly(source)
