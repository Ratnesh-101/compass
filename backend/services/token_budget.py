"""
Compass — Token Budget Management.

Pure, deterministic token budget allocations for direct chat streaming
and autonomous agent reasoning steps.
"""

from __future__ import annotations

from typing import Any, Optional

CONTINUE_PROMPT = (
    "Your previous response was cut off by the token limit. "
    "Continue generating EXACTLY where you left off. "
    "Do not repeat prior paragraphs, table rows, citations, or greetings."
)


def stream_token_budget(tone: Optional[str], max_synth_budget: Any) -> tuple[int, bool]:
    """Return (max_tokens, hard_capped) for the direct chat stream.

    Tone is a style instruction only (enforced by the system prompt). Every tone gets the full
    synthesis budget, because hidden reasoning tokens count against max_tokens and a hard cap
    cuts the visible answer mid-sentence. `hard_capped` is always False and kept for callers.
    """
    return (int(max_synth_budget), False)


def reasoning_token_budget(settings: Any) -> int:
    """Budget for the agent's reasoning / tool-calling step. Never reduced by the chat tone: a truncated tool call or a half answer is worse than a long one; tone is enforced by the system prompt."""
    return int(getattr(settings, "MAX_REASONING_TOKENS", 4096))
