"""Audit tests for PR #219: Question vs Command intent classification bugs."""

import pytest

from backend.router import route_message
from backend.services.task_intent import blocks_task_creation, classify_task_message


@pytest.mark.asyncio
async def test_did_you_remind_me_question_creates_no_task():
    """Bug: Past-tense inquiries like 'Did you remind me...' are classified as commands

    and create tasks in the database instead of answering conversationally.
    """
    msg = "Did you remind me to take medicine yesterday?"
    assert blocks_task_creation(msg) is True, f"blocks_task_creation failed for {msg!r}"
    assert classify_task_message(msg) != "command", f"classified as command: {msg!r}"

    skill, args, _ = await route_message(msg)
    assert skill != "add_task", f"route_message created task {args} for question {msg!r}"


@pytest.mark.asyncio
async def test_should_i_add_task_opinion_question_creates_no_task():
    """Bug: User advice queries like 'Should I add a task for the demo?'

    mistakenly extract 'The demo' as a title and route to add_task.
    """
    msg = "Should I add a task for the demo?"
    assert blocks_task_creation(msg) is True, f"blocks_task_creation failed for {msg!r}"
    assert classify_task_message(msg) != "command", f"classified as command: {msg!r}"

    skill, args, _ = await route_message(msg)
    assert skill != "add_task", f"route_message created task {args} for question {msg!r}"


@pytest.mark.asyncio
async def test_hinglish_capability_question_creates_no_task():
    """Bug: Hinglish capability asks like 'kya tum add task kar sakte ho?'

    extract 'Kar sakte ho' as a task title and route to add_task.
    """
    msg = "kya tum add task kar sakte ho?"
    skill, args, _ = await route_message(msg)
    assert skill != "add_task", f"route_message created task {args} for Hinglish question {msg!r}"


@pytest.mark.asyncio
async def test_quoted_command_in_conversation_creates_no_task():
    """Bug: Conversation messages mentioning a command in quotes create tasks."""
    msg = 'He told me "remind me to call mom tomorrow" during lunch'
    skill, args, _ = await route_message(msg)
    assert skill != "add_task", f"route_message created task {args} for quoted speech {msg!r}"
