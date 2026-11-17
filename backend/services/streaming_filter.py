"""
Compass — Streaming Think Filter.

Filters private reasoning out of streamed model tokens.

Rules (T-009):
- ``<think>`` is reasoning only when it OPENS the message (after optional whitespace). A ``<think>``
  that appears later in an answer is ordinary text (for example an answer that explains the tag).
- Only the few characters needed to recognise an opening ``<think>`` are held back (whitespace and a
  partial tag prefix at the start of the message). Any other text streams immediately. An orphan
  closing tag is not handled specially once text has started streaming.
- ``flush()`` returns everything still held back, except an unfinished reasoning block that opened the
  message (that stays private).
"""

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"

_START, _THINK, _ANSWER = "start", "think", "answer"


class StreamingThinkFilter:
    """Filter reasoning blocks out of streamed model tokens."""

    def __init__(self):
        self.in_think = False
        self.buffer = ""
        self._state = _START

    def process(self, token: str) -> str:
        self.buffer += token
        if self._state == _START:
            return self._process_start()
        if self._state == _THINK:
            return self._process_think()
        return self._process_answer()

    def _process_answer(self) -> str:
        out, self.buffer = self.buffer, ""
        return out

    def _process_start(self) -> str:
        stripped = self.buffer.lstrip()
        if not stripped:
            return ""  # only whitespace so far
        if stripped.startswith(OPEN_TAG):
            self.buffer = stripped[len(OPEN_TAG):]
            self._state = _THINK
            self.in_think = True
            return self._process_think()
        if OPEN_TAG.startswith(stripped):
            return ""  # might still become "<think>"
        self._state = _ANSWER
        return self._process_answer()

    def _process_think(self) -> str:
        idx = self.buffer.find(CLOSE_TAG)
        if idx != -1:
            self.buffer = self.buffer[idx + len(CLOSE_TAG):]
            self._state = _ANSWER
            self.in_think = False
            return self._process_answer()
        keep = 0
        for k in range(min(len(CLOSE_TAG) - 1, len(self.buffer)), 0, -1):
            if self.buffer.endswith(CLOSE_TAG[:k]):
                keep = k
                break
        self.buffer = self.buffer[len(self.buffer) - keep:] if keep else ""
        return ""

    def flush(self) -> str:
        """Return text still held back at end of stream.

        An unfinished reasoning block that opened the message stays private (dropped); anything else
        held back (leading whitespace, a partial '<thi') is returned."""
        if self._state == _THINK:
            self.buffer = ""
            return ""
        tail = self.buffer
        self.buffer = ""
        self._state = _ANSWER
        return tail
