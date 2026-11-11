"""
Compass — Token Budget Management.

Pure, deterministic token budget allocations for direct chat streaming
and autonomous agent reasoning steps.
"""

from __future__ import annotations

from typing import Any, Optional

BRIEF_STREAM_MAX_TOKENS = 500  # visible answer stays short via the tone prompt; the rest is headroom for hidden reasoning
BALANCED_STREAM_MAX_TOKENS = 800
HARD_CAP_FINISH_MAX_TOKENS = 400
HARD_CAP_FINISH_PROMPT = (
    "Your previous response was cut off by the length limit. Finish it now: complete the sentence that was cut off "
    "and conclude in at most two more short sentences. Do not repeat anything you already wrote and do not start a new topic."
)


def stream_token_budget(tone: Optional[str], max_synth_budget: Any) -> tuple[int, bool]:
    """Return (max_tokens, hard_capped) for the direct chat stream. tone may be None."""
    clean_tone = (tone or "").strip().lower()
    if clean_tone == "brief":
        return (BRIEF_STREAM_MAX_TOKENS, True)
    if clean_tone == "balanced":
        return (BALANCED_STREAM_MAX_TOKENS, True)
    return (int(max_synth_budget), False)


def reasoning_token_budget(settings: Any) -> int:
    """Budget for the agent's reasoning / tool-calling step. Never reduced by the chat tone: a truncated tool call or a half answer is worse than a long one; tone is enforced by the system prompt."""
    return int(getattr(settings, "MAX_REASONING_TOKENS", 4096))
