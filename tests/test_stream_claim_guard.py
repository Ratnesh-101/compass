"""Tests for the streaming unbacked-action-claim guard (no DB, no network)."""

import re
from pathlib import Path

import pytest

from backend.services import stream_claim_guard as scg
from backend.services.action_claim_guard import guard_unbacked_action_claims
from backend.services.stream_claim_guard import StreamClaimGuard

PREFIX = "I haven't changed anything yet"
BUFFER_CAP = 20000

CLAIMS = [
    "Updated to 6pm on Thu Nov 26.",
    "Added 1 task: Submit application. It's now on your list.",
    "Task added.",
    "Marked it as done.",
    "Rescheduled it to Friday.",
    "It's now on your schedule.",
    "Done.",
]

HARMLESS = [
    "Would you like me to add this task for Friday?",
    "I can add that if you tell me the date.",
    "Here are your three deadlines: lab Monday. Quiz Tuesday.",
    "You have 4 open tasks.",
    "The Timeline is updated every minute.",
    "To update a task, open it in the Timeline and press Edit.",
    "I have not submitted anything.",
    "Nothing has been added yet.",
]

BENIGN = (
    "Here is how your week looks. You have a lab on Monday and a quiz on Tuesday. "
    "The Timeline shows every deadline in order. Wednesday is free for revision. "
    "Thursday has a group meeting in the afternoon. Friday is light, so plan ahead. "
    "Let me know if you want to look at anything in more detail. "
    "Saturday and Sunday have no classes, so you can rest or catch up on reading. "
    "The library stays open late during the week if you need a quiet place to study. "
)


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
    """Feed tokens; return (guard, replacements, observe_results_after_block)."""
    guard = StreamClaimGuard(**kwargs)
    replacements = []
    after_block = []
    for tok in tokenisations(text)[mode]:
        was_blocked = guard.blocked
        res = guard.observe(tok)
        if res is not None:
            replacements.append(res)
        if was_blocked:
            after_block.append(res)
    fin = guard.finish()
    if fin is not None:
        replacements.append(fin)
    return guard, replacements, after_block


@pytest.mark.parametrize("mode", TOKEN_MODES)
@pytest.mark.parametrize("claim", CLAIMS)
def test_unbacked_claim_yields_one_honest_replacement(claim, mode):
    guard, repl, after_block = run(claim, mode, action_executed=False)
    assert len(repl) == 1, f"input={claim!r} replacements={repl!r}"
    assert repl[0].startswith(PREFIX)
    assert guard.blocked is True
    assert all(r is None for r in after_block)
    assert guard.observe("more text. ") is None
    assert guard.final_text() == repl[0]


@pytest.mark.parametrize("mode", TOKEN_MODES)
@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_text_is_never_replaced(text, mode):
    guard, repl, _ = run(text, mode, action_executed=False)
    assert repl == [], f"input={text!r} replacements={repl!r}"
    assert guard.finish() is None
    assert guard.blocked is False
    assert guard.final_text() == text


@pytest.mark.parametrize("mode", TOKEN_MODES)
def test_late_claim_after_long_benign_text_is_replaced(mode):
    assert len(BENIGN) > 300
    original = BENIGN + "I've updated your deadline to Friday."
    guard, repl, _ = run(original, mode, action_executed=False)
    assert len(repl) == 1
    assert PREFIX in repl[0]
    assert guard.blocked is True
    assert guard.final_text() == repl[0]


@pytest.mark.parametrize("mode", TOKEN_MODES)
def test_replacement_is_returned_only_once(mode):
    text = "Task added. Marked it as done. I've updated your deadline to Friday. Done."
    guard, repl, _ = run(text, mode, action_executed=False)
    assert len(repl) == 1
    assert guard.finish() is None
    assert guard.final_text() == repl[0]


@pytest.mark.parametrize("mode", TOKEN_MODES)
@pytest.mark.parametrize("claim", CLAIMS)
def test_action_executed_never_replaces(claim, mode):
    guard, repl, _ = run(claim, mode, action_executed=True)
    assert repl == []
    assert guard.finish() is None
    assert guard.blocked is False
    assert guard.final_text() == claim


def test_memory_is_bounded_on_very_long_stream():
    guard = StreamClaimGuard(action_executed=False)
    token = "lorem ipsum "[:10]
    for _ in range(10000):
        guard.observe(token)
    guard.finish()
    final = guard.final_text()
    assert isinstance(final, str)
    cap = max(
        [
            v
            for k, v in vars(scg).items()
            if k.isupper()
            and isinstance(v, int)
            and not isinstance(v, bool)
            and ("MAX" in k or "CAP" in k or "LIMIT" in k)
        ]
        or [BUFFER_CAP]
    )
    assert len(final) <= max(cap, BUFFER_CAP) + 1000
    assert len(final) < 100000


@pytest.mark.parametrize("claim", CLAIMS)
def test_honest_text_is_idempotent_under_guard(claim):
    honest, replaced = guard_unbacked_action_claims(claim, False)
    assert replaced is True
    second, replaced_again = guard_unbacked_action_claims(honest, False)
    assert second == honest
    assert replaced_again is False


def test_chat_stream_wires_guard():
    source = (
        Path(__file__).resolve().parent.parent / "backend" / "services" / "chat_stream.py"
    ).read_text(encoding="utf-8")
    assert "StreamClaimGuard" in source
    assert "claim_guard.observe" in source
    assert "claim_guard.finish" in source
    assert "'replace'" in source
