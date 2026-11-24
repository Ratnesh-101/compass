"""Tests for the unbacked-action-claim guard.

The guard replaces replies that claim a completed action when no tool
actually executed one. Offers, questions and read-only answers must pass.
"""

from pathlib import Path

import pytest

from backend.services.action_claim_guard import guard_unbacked_action_claims

PREFIX = "I haven't changed anything yet"

CLAIMS = [
    "Updated the task: Submit DBMS lab \u2014 Wed Nov 25 at 6 PM",
    "Done\u2014I've added a high-priority task for today",
    "I've updated your deadline to Friday.",
    "I have scheduled the task for 3 PM.",
    "Task added.",
    "Your task has been scheduled.",
    "All set! I submitted your application.",
    "I went ahead and deleted it.",
    "Done.",
]

NON_CLAIMS = [
    "Would you like me to add this task for Friday?",
    "I can add that task if you tell me the date.",
    "Do you want me to update the deadline?",
    "Here are your three deadlines: DBMS lab, Maths quiz, Essay.",
    "You have 4 open tasks.",
    "I could not find a task named groceries.",
    "To update a task, open it in the Timeline and press Edit.",
    "The Timeline is updated every minute.",
]


@pytest.mark.parametrize("reply", CLAIMS)
def test_executed_action_returns_reply_unchanged(reply):
    text, replaced = guard_unbacked_action_claims(reply, True)
    assert text == reply
    assert replaced is False


@pytest.mark.parametrize("reply", CLAIMS)
def test_unbacked_claim_is_replaced(reply):
    text, replaced = guard_unbacked_action_claims(reply, False)
    assert replaced is True
    assert text.startswith(PREFIX)
    assert text != reply


@pytest.mark.parametrize("reply", NON_CLAIMS)
def test_offers_questions_and_answers_are_not_replaced(reply):
    text, replaced = guard_unbacked_action_claims(reply, False)
    assert text == reply
    assert replaced is False


@pytest.mark.parametrize(
    "reply",
    [
        "Task added.",
        "I've updated your deadline to Friday.",
        "I have scheduled the task for 3 PM.",
        "Your task has been scheduled.",
    ],
)
def test_task_claim_mentions_confirmation_card(reply):
    text, replaced = guard_unbacked_action_claims(reply, False)
    assert replaced is True
    assert text.startswith(PREFIX)
    assert "confirmation card" in text


def test_submit_claim_says_nothing_submitted_and_points_to_career_tab():
    text, replaced = guard_unbacked_action_claims(
        "All set! I submitted your application.", False
    )
    assert replaced is True
    assert text.startswith(PREFIX)
    assert "nothing has been submitted" in text
    assert "Career" in text


def test_harmless_leading_sentence_is_preserved():
    text, replaced = guard_unbacked_action_claims(
        "Sure thing. Updated the task to 6 PM.", False
    )
    assert replaced is True
    assert text.startswith("Sure thing.")
    assert "Updated the task to 6 PM" not in text


@pytest.mark.parametrize("reply", CLAIMS + ["Sure thing. Updated the task to 6 PM."])
def test_guard_is_idempotent(reply):
    first, replaced = guard_unbacked_action_claims(reply, False)
    assert replaced is True
    second, replaced_again = guard_unbacked_action_claims(first, False)
    assert second == first
    assert replaced_again is False


def test_orchestrator_imports_and_calls_guard():
    source = (
        Path(__file__).resolve().parent.parent / "backend" / "orchestrator.py"
    ).read_text(encoding="utf-8")
    assert "action_claim_guard" in source
    assert "import" in source
    assert "guard_unbacked_action_claims(" in source
    assert source.count("guard_unbacked_action_claims") >= 2
