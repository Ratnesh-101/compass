"""Tests for PR #219 task-intent variants: false-negative fixes, guard messages, and quote stripping."""

import pytest

from backend.router import route_message
from backend.router_helpers import _extract_task_creation_args, is_explicit_task_creation
from backend.services.task_intent import (
    _strip_quoted_text,
    blocks_task_creation,
    classify_task_message,
    normalize_task_intent_text,
)


# 12 False-negative messages from the audit table with their expected sensible titles
AUDIT_FALSE_NEGATIVES = [
    ("ad task buy milk tomorow", "Buy milk"),
    ("craete task submit report by friday", "Submit report"),
    ("shedule task demo for monday", "Demo"),
    ("remind mee to call mom at 5pm", "Call mom"),
    ("can u add a taks to review PR?", "review PR"),
    ("add taks finish slides", "Finish slides"),
    ("create a tsak: write tests", "Write tests"),
    ("mujhe remind kar dena to call mom tomorrow", "Call mom"),
    ("ek task add kar do: buy groceries", "Buy groceries"),
    ("yeh task list me daal do please: finish thesis", "Finish thesis"),
    ("please remind me ki assign submit karna hai kal", "Assign submit karna hai"),
    ("Would you mind creating a deadline for project demo on Friday?", "Project demo"),
]

# 18 Must-not-create guard messages (capability asks, questions, quotes, incomplete commands)
MUST_NOT_CREATE_GUARDS = [
    "can you add tasks?",
    "kya tum add task kar sakte ho?",
    "kya tum add task kar sakte ho",
    "Did you remind me to take medicine yesterday?",
    "Do you think I should add a task to study?",
    "Should I add a task for the demo?",
    'He told me "remind me to call mom tomorrow" during lunch',
    'Can you explain why the command "add task buy milk tomorrow" created a task?',
    'I was reading a tutorial that said "create a task for your team" every morning.',
    "can I add a reminder?",
    "could you create a task for me?",
    "add deadlines for me",
    "add a task",
    "create a task for tomorrow",
    "please add a reminder",
    "what tasks do I have due today?",
    "when is the project demo due?",
    "how do I add a task?",
]


@pytest.mark.parametrize("message, expected_title", AUDIT_FALSE_NEGATIVES)
def test_audit_false_negatives_extract_sensible_title(message, expected_title):
    """Every false-negative command from the audit table extracts a valid task title."""
    assert blocks_task_creation(message) is False, f"blocks_task_creation unexpectedly True for {message!r}"
    assert is_explicit_task_creation(message) is True, f"is_explicit_task_creation failed for {message!r}"

    args = _extract_task_creation_args(message)
    actual_title = args.get("title", "")
    assert actual_title == expected_title, (
        f"Title mismatch for {message!r}: expected {expected_title!r}, got {actual_title!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("message, expected_title", AUDIT_FALSE_NEGATIVES)
async def test_audit_false_negatives_route_to_add_task(message, expected_title):
    """Every false-negative command routes directly to add_task with sensible extracted fields."""
    skill, args, _ = await route_message(message)
    assert skill == "add_task", f"route_message failed to route to add_task for {message!r}: got {skill!r}"
    assert args.get("title") == expected_title, (
        f"Routed task title mismatch for {message!r}: expected {expected_title!r}, got {args.get('title')!r}"
    )


@pytest.mark.parametrize("message", MUST_NOT_CREATE_GUARDS)
def test_must_not_create_guards_classification(message):
    """Guard messages must be blocked from task creation or rejected by lack of title."""
    if blocks_task_creation(message):
        assert classify_task_message(message) == "question"
    else:
        # If not blocked as question (e.g. empty command 'add a task'), title must be empty
        title = _extract_task_creation_args(message).get("title", "")
        assert not title, f"Incomplete command {message!r} unexpectedly extracted title {title!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", MUST_NOT_CREATE_GUARDS)
async def test_must_not_create_guards_route_message(message):
    """Guard messages must never create a task via route_message."""
    skill, args, _ = await route_message(message)
    assert skill != "add_task", f"Guard message {message!r} unexpectedly routed to add_task with {args}"


def test_strip_quoted_text_trailing_apostrophe_does_not_open_span():
    """A trailing apostrophe after an alphanumeric word (e.g. users', parents') must not open a quoted span."""
    assert _strip_quoted_text("the users' tasks") == "the users' tasks"
    assert _strip_quoted_text("my parents' birthday") == "my parents' birthday"
    assert _strip_quoted_text("James' presentation") == "James' presentation"
    assert _strip_quoted_text("don't forget the meeting") == "don't forget the meeting"


def test_strip_quoted_text_still_strips_actual_quoted_spans():
    """Legitimate single and double quotes are still stripped from conversational text."""
    stripped_double = _strip_quoted_text('He said "create a task" then left')
    assert "create a task" not in stripped_double
    assert "He said" in stripped_double

    stripped_single = _strip_quoted_text("He said 'create a task' then left")
    assert "create a task" not in stripped_single
    assert "He said" in stripped_single


def test_normalize_task_intent_handles_50k_adversarial_timing():
    """Adversarial 50,000-character inputs of repeated verbs run in well under 100 ms."""
    import time

    adversarial_inputs = [
        "add " * 12500,
        "ad " * 16666,
        "kar " * 12500,
        "create " * 7500,
    ]
    for inp in adversarial_inputs:
        t0 = time.perf_counter()
        _ = normalize_task_intent_text(inp)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 100, f"Normalization took {elapsed_ms:.2f} ms on 50k chars (limit 100 ms)"
