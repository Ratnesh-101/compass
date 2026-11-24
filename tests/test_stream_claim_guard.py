"""Tests for the streaming unbacked-action-claim guard (no DB, no network)."""

import re
from pathlib import Path

import pytest

from backend.services import stream_claim_guard as scg
from backend.services.action_claim_guard import guard_unbacked_action_claims
from backend.services.stream_claim_guard import StreamClaimGuard

PREFIX = "I haven't changed anything yet"
CORRECTION_START = "\n\n(Correction: I haven't changed anything yet"

CLAIMS = [
    "Updated to 6pm on Thu Nov 26.",
    "Added 1 task: Submit DBMS lab. It's now on your list.",
    "Task added.",
    "Marked it as done.",
    "Rescheduled it to Friday.",
    "It's now on your schedule.",
    "I've updated your deadline to Friday.",
    "Done.",
]

HARMLESS = [
    "Would you like me to add this task for Friday?",
    "I can add that if you tell me the date.",
    "Here are your three deadlines",
    "You have 4 open tasks.",
    "The Timeline is updated every minute.",
    "To update a task, open it in the Timeline and press Edit.",
    "I have not submitted anything.",
    "Nothing has been added yet.",
]


def split_chars(text, size):
    return [text[i : i + size] for i in range(0, len(text), size)]


def split_words(text):
    return re.findall(r"\S+\s*|\s+", text)


def tokenisations(text):
    out = {f"chars{n}": split_chars(text, n) for n in range(1, 6)}
    out["words"] = split_words(text)
    return out


TOKEN_MODES = list(tokenisations("a b c"))


def run(text, mode, **kwargs):
    guard = StreamClaimGuard(**kwargs)
    chunks = []
    for tok in tokenisations(text)[mode]:
        chunks.extend(guard.feed(tok))
    chunks.extend(guard.finish())
    return guard, "".join(chunks)


@pytest.mark.parametrize("mode", TOKEN_MODES)
@pytest.mark.parametrize("claim", CLAIMS)
def test_unbacked_claim_is_replaced_with_honest_text(claim, mode):
    honest, replaced = guard_unbacked_action_claims(claim, False)
    assert replaced is True
    guard, out = run(claim, mode, action_executed=False)
    assert out == honest
    assert out.startswith(PREFIX)
    assert out.count(PREFIX) == 1
    assert claim not in out
    assert guard.final_text() == out


@pytest.mark.parametrize("mode", TOKEN_MODES)
@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_text_passes_through_unchanged(text, mode):
    guard, out = run(text, mode, action_executed=False)
    assert out == text
    assert guard.final_text() == text


BENIGN = (
    "Here is how your week looks. You have a lab on Monday and a quiz on Tuesday. "
    "The Timeline shows every deadline in order. Wednesday is free for revision. "
    "Thursday has a group meeting in the afternoon. Friday is light, so plan ahead. "
    "Let me know if you want to look at anything in more detail. "
    "The weekend is open, so you can rest or catch up on reading. "
    "Remember to drink water and take short breaks between study sessions. "
)


@pytest.mark.parametrize("mode", TOKEN_MODES)
def test_late_claim_is_corrected_after_streaming(mode):
    assert len(BENIGN) > 300
    claim = "I've updated your deadline to Friday."
    original = BENIGN + claim
    guard = StreamClaimGuard(action_executed=False, hold_chars=220)
    streamed = []
    for tok in tokenisations(original)[mode]:
        streamed.extend(guard.feed(tok))
    tail = guard.finish()
    assert len(tail) == 1
    assert tail[0].startswith(CORRECTION_START)
    assert "".join(streamed).startswith(BENIGN[:200])
    assert guard.final_text() == original + tail[0]


def test_hold_back_before_hold_chars_without_sentence_end():
    text = "word " * 30  # 150 chars, no sentence end
    guard = StreamClaimGuard(action_executed=False, hold_chars=220)
    released = []
    for tok in split_chars(text, 3):
        assert guard.feed(tok) == []
    released.extend(guard.finish())
    assert "".join(released) == text
    assert guard.final_text() == text


def test_short_reply_is_released_by_finish_unchanged():
    text = "Your lab is on Monday at 10 AM."
    guard = StreamClaimGuard(action_executed=False, hold_chars=220)
    out = []
    for tok in split_chars(text, 4):
        out.extend(guard.feed(tok))
    out.extend(guard.finish())
    assert "".join(out) == text
    assert guard.final_text() == text


@pytest.mark.parametrize("claim", CLAIMS)
def test_action_executed_disables_checks(claim):
    guard = StreamClaimGuard(action_executed=True, hold_chars=220)
    out = []
    for tok in split_chars(claim, 3):
        out.extend(guard.feed(tok))
    assert guard.finish() == []
    out_text = "".join(out)
    assert out_text == claim
    assert guard.final_text() == claim


@pytest.mark.parametrize("claim", CLAIMS)
def test_widened_guard_is_idempotent_on_honest_text(claim):
    first, replaced = guard_unbacked_action_claims(claim, False)
    assert replaced is True
    second, replaced_again = guard_unbacked_action_claims(first, False)
    assert second == first
    assert replaced_again is False


def _documented_cap():
    caps = [
        v
        for k, v in vars(scg).items()
        if isinstance(v, int)
        and not isinstance(v, bool)
        and k.isupper()
        and ("MAX" in k or "CAP" in k or "LIMIT" in k)
    ]
    return max(caps) if caps else None


def test_memory_is_bounded_on_very_long_stream():
    guard = StreamClaimGuard(action_executed=False, hold_chars=220)
    token = "lorem ipsum "[:10]
    for _ in range(10000):
        guard.feed(token)
    guard.finish()
    final = guard.final_text()
    assert isinstance(final, str)
    cap = _documented_cap()
    assert cap is not None, "module must define a documented cap constant"
    assert len(final) <= cap + 1000
    assert len(final) < 100000


def test_chat_stream_wires_guard():
    source = (
        Path(__file__).resolve().parent.parent / "backend" / "services" / "chat_stream.py"
    ).read_text(encoding="utf-8")
    assert "StreamClaimGuard" in source
    assert "import" in source
    assert ".feed(" in source
    assert ".finish(" in source
