"""Deterministic pre-LLM chat checks must not hijack ordinary requests."""

from __future__ import annotations

import pytest

from backend.router_helpers import (
    is_chat_delete_intent,
    is_pending_action_cancel,
    is_pending_action_confirm,
)
from backend.services.delete_target import normalize_delete_target


@pytest.mark.parametrize(
    "message",
    [
        "remove the bug from my code",
        "drop me a summary of my day",
        "delete the old branch from git",
        "remove duplicates from this list",
        "drop it like it's hot",
    ],
)
def test_non_task_requests_are_not_delete_intents(message):
    assert is_chat_delete_intent(message)[0] is False


@pytest.mark.parametrize(
    "message, target",
    [
        ("please delete the pitch deck task", "pitch deck"),
        ("can you delete tasks?", "tasks"),
        ("could you remove my deadline please", "my deadline"),
        ("I want to delete test", "test"),
        ("delete test", "test"),
        ("remove the hackathon task", "hackathon"),
        ("drop the essay task", "essay"),
    ],
)
def test_polite_and_plain_delete_requests_are_recognised(message, target):
    is_del, is_clear, got = is_chat_delete_intent(message)
    assert is_del is True and is_clear is False
    assert got == target


@pytest.mark.parametrize(
    "message",
    [
        "confirm my meeting time is 3pm",
        "confirm the booking for friday",
        "yes, I need help with my essay",
        "yes I need help with my essay",
    ],
)
def test_ordinary_requests_are_not_confirmations(message):
    assert is_pending_action_confirm(message) is False


@pytest.mark.parametrize(
    "message",
    ["cancel my gym membership how", "cancel culture essay ideas", "no, I want a different plan for friday"],
)
def test_ordinary_requests_are_not_cancellations(message):
    assert is_pending_action_cancel(message) is False


@pytest.mark.parametrize("message", ["yes", "confirm", "Confirm delete", "yes, delete it", "confirm it", "yes please", "sure"])
def test_real_confirmations_still_work(message):
    assert is_pending_action_confirm(message) is True


@pytest.mark.parametrize("message", ["cancel", "cancel it", "cancel action", "no, don't delete", "no", "never mind", "stop"])
def test_real_cancellations_still_work(message):
    assert is_pending_action_cancel(message) is True


@pytest.mark.parametrize("raw", ["my last task", "the latest deadline", "most recent task"])
def test_position_words_are_generic(raw):
    assert normalize_delete_target(raw) == ("", True)


@pytest.mark.parametrize("message", ["Please delete all my tasks", "can you clear my schedule", "delete all my tasks please"])
def test_polite_clear_all_is_still_clear_all(message):
    assert is_chat_delete_intent(message) == (True, True, "")
