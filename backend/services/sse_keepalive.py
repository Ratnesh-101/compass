"""Keep an SSE stream alive while the producer is silent.

A reasoning model can take tens of seconds before its first token, and a tool step can be silent
for longer. Proxies (Vercel rewrite -> Render) drop connections that send no bytes, which the user
sees as "Understanding your request..." forever or "Stream interrupted". This wrapper yields an SSE
comment line (ignored by clients) whenever the source has been quiet for `interval` seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

KEEPALIVE_INTERVAL_SECONDS = 8.0
KEEPALIVE_FRAME = ": ping\n\n"


async def with_keepalive(
    source: AsyncIterator[str], interval: float = KEEPALIVE_INTERVAL_SECONDS
) -> AsyncIterator[str]:
    iterator = source.__aiter__()
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield KEEPALIVE_FRAME
                continue
            finished, pending = pending, None
            try:
                item = finished.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()
