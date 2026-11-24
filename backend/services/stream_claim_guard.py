"""Stream Claim Guard.

Guards SSE token streaming against unbacked action completion claims.
Observes tokens as they are streamed and replaces the output with an
honest confirmation request if an unbacked action claim is detected.
"""

from __future__ import annotations

from typing import Optional

from backend.services.action_claim_guard import guard_unbacked_action_claims

MAX_BUFFER_LEN = 20000


class StreamClaimGuard:
    """Stream-aware claim guard for assistant responses."""

    def __init__(
        self, action_executed: bool = False, check_every_chars: int = 40
    ) -> None:
        self.action_executed = action_executed
        self.check_every_chars = check_every_chars
        self._blocked = False
        self._buffer = ""
        self._honest_text: Optional[str] = None
        self._last_checked_pos = 0
        self._seen_sentence_end = False

    @property
    def blocked(self) -> bool:
        """True after a replacement: the caller must stop emitting tokens."""
        return self._blocked

    def observe(self, token: str) -> Optional[str]:
        """Observe a streamed token and return honest replacement text if a claim is found."""
        if not token:
            return None

        if len(self._buffer) < MAX_BUFFER_LEN:
            self._buffer += token[: MAX_BUFFER_LEN - len(self._buffer)]

        if self.action_executed or self._blocked:
            return None

        has_new_sentence_end = (
            token.endswith((".", "!", "?"))
            or any(
                sep in self._buffer[self._last_checked_pos :]
                for sep in (". ", "! ", "? ", "\n")
            )
        )

        should_check = False
        if has_new_sentence_end:
            self._seen_sentence_end = True
            should_check = True
        elif (
            len(self._buffer) - self._last_checked_pos >= self.check_every_chars
            and not self._seen_sentence_end
            and len(self._buffer) <= 200
        ):
            should_check = True

        if not should_check:
            return None

        self._last_checked_pos = len(self._buffer)
        guarded_text, was_replaced = guard_unbacked_action_claims(
            self._buffer, False
        )
        if was_replaced:
            self._blocked = True
            self._honest_text = guarded_text
            return guarded_text
        return None

    def finish(self) -> Optional[str]:
        """Finalize the stream and check full buffer if not already blocked."""
        if self._blocked or self.action_executed:
            return None
        if not self._buffer:
            return None
        self._last_checked_pos = len(self._buffer)
        guarded_text, was_replaced = guard_unbacked_action_claims(
            self._buffer, False
        )
        if was_replaced:
            self._blocked = True
            self._honest_text = guarded_text
            return guarded_text
        return None

    def final_text(self, raw_fallback: str = "") -> str:
        """Return the honest text when blocked, else the accumulated text or fallback."""
        if self._blocked and self._honest_text is not None:
            return self._honest_text
        return self._buffer if self._buffer else raw_fallback
