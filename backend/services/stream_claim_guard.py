"""Stream Claim Guard.

Guards SSE token streaming against unbacked action completion claims.
Buffers early tokens to detect unbacked claims before emitting to the client,
or appends a late correction if a claim appears later in the stream.
"""

from __future__ import annotations

from typing import List

from backend.services.action_claim_guard import guard_unbacked_action_claims

LATE_CORRECTION = (
    "\n\n(Correction: I haven't changed anything yet. "
    "Tell me exactly what you want and I'll show a confirmation card first.)"
)
MAX_FULL_TEXT_LEN = 20000


class StreamClaimGuard:
    """Stream-aware claim guard for assistant responses."""

    def __init__(self, action_executed: bool = False, hold_chars: int = 220) -> None:
        self.action_executed = action_executed
        self.hold_chars = hold_chars
        self._state = "PASS" if action_executed else "HOLD"
        self._buffer = ""
        self._full_text = ""
        self._honest_text = ""
        self._replaced = False
        self._late_correction = ""

    @property
    def replaced(self) -> bool:
        """Whether a claim was detected and replaced/corrected."""
        return self._replaced

    def feed(self, token: str) -> List[str]:
        """Feed a token into the guard and return chunks allowed to be emitted now."""
        if not token:
            return []

        # Bounded memory: keep a running copy of the full text up to 20000 chars
        if len(self._full_text) < MAX_FULL_TEXT_LEN:
            self._full_text += token[: MAX_FULL_TEXT_LEN - len(self._full_text)]

        if self.action_executed:
            return [token]

        if self._state == "BLOCKED":
            # Swallow every later token
            return []

        if self._state == "PASS":
            # Later tokens are returned unchanged
            return [token]

        # HOLD state
        self._buffer += token
        has_sentence_end = (
            ". " in self._buffer
            or "! " in self._buffer
            or "? " in self._buffer
            or "\n" in self._buffer
        )

        if len(self._buffer) < self.hold_chars and not has_sentence_end:
            return []

        # Released from hold
        guarded_text, was_replaced = guard_unbacked_action_claims(
            self._buffer, self.action_executed
        )
        if was_replaced:
            self._state = "BLOCKED"
            self._replaced = True
            self._honest_text = guarded_text
            self._buffer = ""
            return [guarded_text]

        self._state = "PASS"
        out = [self._buffer]
        self._buffer = ""
        return out

    def finish(self) -> List[str]:
        """Finalize the stream and return any remaining chunks."""
        if self.action_executed:
            return []

        if self._state == "HOLD":
            if not self._buffer:
                return []
            guarded_text, was_replaced = guard_unbacked_action_claims(
                self._buffer, self.action_executed
            )
            if was_replaced:
                self._state = "BLOCKED"
                self._replaced = True
                self._honest_text = guarded_text
                self._buffer = ""
                return [guarded_text]
            self._state = "PASS"
            out = [self._buffer]
            self._buffer = ""
            return out

        if self._state == "PASS":
            if self._late_correction:
                return []
            # Run the guard on the FULL text once
            _, was_replaced = guard_unbacked_action_claims(
                self._full_text, self.action_executed
            )
            if was_replaced:
                self._replaced = True
                self._late_correction = LATE_CORRECTION
                return [LATE_CORRECTION]
            return []

        # If BLOCKED, honest_text was already emitted, nothing more to return
        return []

    def final_text(self) -> str:
        """Return what the user actually saw (for persistence)."""
        if self.action_executed:
            return self._full_text

        if self._state == "BLOCKED":
            return self._honest_text

        if self._late_correction:
            return self._full_text + self._late_correction

        return self._full_text
