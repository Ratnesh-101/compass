import asyncio

import pytest

from backend.services.sse_keepalive import KEEPALIVE_FRAME, with_keepalive


async def _collect(gen):
    return [item async for item in gen]


@pytest.mark.asyncio
async def test_pings_are_sent_while_the_source_is_silent():
    async def slow():
        await asyncio.sleep(0.35)
        yield "data: first\n\n"
        yield "data: second\n\n"

    items = await _collect(with_keepalive(slow(), interval=0.05))
    assert items[-2:] == ["data: first\n\n", "data: second\n\n"]
    assert items.count(KEEPALIVE_FRAME) >= 3
    assert all(i == KEEPALIVE_FRAME for i in items[:-2])


@pytest.mark.asyncio
async def test_fast_source_gets_no_extra_pings():
    async def fast():
        for i in range(3):
            yield f"data: {i}\n\n"

    assert await _collect(with_keepalive(fast(), interval=5)) == ["data: 0\n\n", "data: 1\n\n", "data: 2\n\n"]


@pytest.mark.asyncio
async def test_source_errors_propagate():
    async def boom():
        yield "data: ok\n\n"
        raise RuntimeError("upstream failed")

    seen = []
    with pytest.raises(RuntimeError):
        async for item in with_keepalive(boom(), interval=5):
            seen.append(item)
    assert seen == ["data: ok\n\n"]


@pytest.mark.asyncio
async def test_closing_early_stops_the_source():
    state = {"closed": False}

    async def endless():
        try:
            while True:
                await asyncio.sleep(0.01)
                yield "data: tick\n\n"
        finally:
            state["closed"] = True

    gen = with_keepalive(endless(), interval=5)
    assert await gen.__anext__() == "data: tick\n\n"
    await gen.aclose()
    assert state["closed"] is True
