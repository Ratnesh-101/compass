"""with_keepalive must keep ContextVars that the wrapped stream sets for its later steps."""

from __future__ import annotations

import asyncio
import contextvars

import pytest

from backend.services.sse_keepalive import with_keepalive

_FLAG: contextvars.ContextVar[str] = contextvars.ContextVar("sse_keepalive_test_flag", default="unset")


async def _source():
    _FLAG.set("set-inside-stream")  # the agent endpoint does exactly this with include_demo
    yield "first"
    await asyncio.sleep(0.05)
    yield f"second:{_FLAG.get()}"
    yield f"third:{_FLAG.get()}"


@pytest.mark.asyncio
async def test_value_set_inside_the_stream_is_visible_to_later_steps():
    frames = [frame async for frame in with_keepalive(_source(), interval=0.01) if not frame.startswith(":")]
    assert frames == ["first", "second:set-inside-stream", "third:set-inside-stream"]


@pytest.mark.asyncio
async def test_values_set_before_the_wrapper_are_still_visible_inside():
    token = _FLAG.set("set-by-caller")
    try:

        async def reader():
            yield f"seen:{_FLAG.get()}"

        frames = [frame async for frame in with_keepalive(reader(), interval=0.01)]
        assert frames == ["seen:set-by-caller"]
    finally:
        _FLAG.reset(token)


@pytest.mark.asyncio
async def test_keepalive_frames_are_still_emitted_while_the_source_is_quiet():
    async def slow():
        await asyncio.sleep(0.12)
        yield "late"

    frames = [frame async for frame in with_keepalive(slow(), interval=0.02)]
    assert frames[-1] == "late"
    assert any(f.startswith(":") for f in frames[:-1])


@pytest.mark.asyncio
async def test_source_errors_still_propagate():
    async def boom():
        yield "ok"
        raise ValueError("source failed")

    seen = []
    with pytest.raises(ValueError):
        async for frame in with_keepalive(boom(), interval=0.01):
            seen.append(frame)
    assert "ok" in seen
