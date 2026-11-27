"""Read-only answers (plans, due lists) must pass the claim guards untouched (no DB, no network)."""

import time

import pytest

from backend.services.action_claim_guard import guard_unbacked_action_claims
from backend.services.stream_claim_guard import StreamClaimGuard

TABLE_HEADER = "| Task | Domain | Scheduled Slot | Due Date | Priority |"
TABLE_SEP = "|---|---|---|---|---|"
ROW_1 = "| Buy groceries | General | Fri Nov 27, 2:30-3:30 PM | Sat Nov 28 | Medium |"
ROW_2 = "| Call the bank | Personal | Fri Nov 27, 4:00-4:30 PM | Sat Nov 28 | High |"

PLAN = (
    "Here is a realistic weekly plan.\n\n"
    f"{TABLE_HEADER}\n{TABLE_SEP}\n{ROW_1}\n{ROW_2}\n\n"
    "Nothing is saved yet. Say commit this plan to put these blocks on your calendar."
)

DUE_LIST = (
    "**Due tomorrow (Saturday, November 28):**\n"
    "- Call the bank (due Sat Nov 28, 5:00 PM)\n\n"
    "Nothing is scheduled for Saturday, November 28 yet."
)

HONEST = {"plan": PLAN, "due_list": DUE_LIST}

FALSE_CLAIMS = [
    "I have scheduled your tasks for Monday.",
    "Done: I added the task.",
    "Updated task: 1. Submit DBMS lab - Thu Nov 26 6 PM",
    "Research area created.",
]

MIXED_CLAIM = "I have scheduled your tasks for Monday."
MIXED = (
    "Here is a realistic weekly plan.\n\n"
    f"{TABLE_HEADER}\n{TABLE_SEP}\n{ROW_1}\n{ROW_2}\n\n"
    f"{MIXED_CLAIM}\n"
    "Say commit this plan to put these blocks on your calendar."
)


def stream(text, size=20):
    guard = StreamClaimGuard()
    events = []
    for i in range(0, len(text), size):
        res = guard.observe(text[i : i + size])
        if res is not None:
            events.append(res)
    fin = guard.finish()
    if fin is not None:
        events.append(fin)
    return guard, events


@pytest.mark.parametrize("name", list(HONEST))
def test_honest_read_only_answer_unchanged(name):
    text = HONEST[name]
    out, replaced = guard_unbacked_action_claims(text, False)
    assert replaced is False
    assert out == text


@pytest.mark.parametrize("claim", FALSE_CLAIMS)
def test_false_claims_still_replaced(claim):
    out, replaced = guard_unbacked_action_claims(claim, False)
    assert replaced is True
    assert out != claim
    assert "I haven't changed anything yet" in out


def test_mixed_reply_keeps_honest_sentences_and_table():
    out, replaced = guard_unbacked_action_claims(MIXED, False)
    assert replaced is True
    assert MIXED_CLAIM not in out
    assert "Here is a realistic weekly plan." in out
    for line in (TABLE_HEADER, ROW_1, ROW_2):
        assert line in out
    assert "Say commit this plan to put these blocks on your calendar." in out


@pytest.mark.parametrize("name", list(HONEST))
def test_stream_honest_text_unchanged_no_replace_event(name):
    text = HONEST[name]
    guard, events = stream(text)
    assert events == []
    assert guard.blocked is False
    assert guard.final_text() == text


@pytest.mark.parametrize("claim", FALSE_CLAIMS)
def test_stream_false_claim_replaced(claim):
    guard, events = stream(claim)
    assert len(events) >= 1
    assert guard.blocked is True
    assert guard.final_text() != claim
    assert "I haven't changed anything yet" in guard.final_text()


def test_stream_mixed_reply_not_left_raw():
    guard, events = stream(MIXED)
    assert events
    assert MIXED_CLAIM not in guard.final_text()


def test_large_honest_answer_is_fast():
    sentence = "The Timeline shows every deadline in order. "
    text = (sentence * (100000 // len(sentence) + 1))[:100000]
    assert len(text) == 100000

    start = time.perf_counter()
    out, replaced = guard_unbacked_action_claims(text, False)
    assert time.perf_counter() - start < 2.0
    assert replaced is False and out == text

    start = time.perf_counter()
    guard, events = stream(text)
    guard.finish()
    assert time.perf_counter() - start < 2.0
    assert events == []
