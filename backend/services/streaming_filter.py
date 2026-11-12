"""
Compass — Streaming Think Filter.

Filters out <think>...</think> reasoning blocks from streamed model tokens.
"""

class StreamingThinkFilter:
    """Filter out <think>...</think> reasoning blocks from streamed model tokens."""

    def __init__(self):
        self.in_think = False
        self.buffer = ""

    def process(self, token: str) -> str:
        self.buffer += token
        out = ""
        while self.buffer:
            if not self.in_think:
                if "<think>" in self.buffer:
                    idx = self.buffer.index("<think>")
                    out += self.buffer[:idx]
                    self.buffer = self.buffer[idx + len("<think>"):]
                    self.in_think = True
                else:
                    match_pos = -1
                    for i in range(len(self.buffer)):
                        if "<think>".startswith(self.buffer[i:]):
                            match_pos = i
                            break
                    if match_pos != -1:
                        out += self.buffer[:match_pos]
                        self.buffer = self.buffer[match_pos:]
                        break
                    else:
                        out += self.buffer
                        self.buffer = ""
            else:
                if "</think>" in self.buffer:
                    idx = self.buffer.index("</think>")
                    self.buffer = self.buffer[idx + len("</think>"):]
                    self.in_think = False
                else:
                    match_pos = -1
                    for i in range(len(self.buffer)):
                        if "</think>".startswith(self.buffer[i:]):
                            match_pos = i
                            break
                    if match_pos != -1:
                        self.buffer = self.buffer[match_pos:]
                    else:
                        self.buffer = ""
                    break
        return out

    def flush(self) -> str:
        """Return text still held back at end of stream (e.g. a trailing '<th' that never became <think>).

        Text inside an unfinished <think> block is private reasoning and stays dropped."""
        tail = "" if self.in_think else self.buffer
        self.buffer = ""
        return tail
