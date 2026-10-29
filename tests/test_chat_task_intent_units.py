"""Unit tests for chat task-intake guards, list parsing and timezone-aware due dates (no database)."""

from datetime import datetime, timezone

import pytest

from backend.router_helpers import _extract_task_creation_args, is_task_mutation_request
from backend.services.task_intake_parse import MAX_ITEMS, parse_task_list
from backend.services.task_intent import (
    COMMAND,
    QUESTION,
    STATEMENT,
    blocks_task_creation,
    classify_task_message,
    is_capability_question,
    is_intake_intent,
    title_problem,
)
from backend.services.task_time import (
    extract_clock,
    is_valid_timezone,
    local_today,
    pick_timezone,
    resolve_due,
)

PASTE = (
    "Title | Domain | Due | Priority | Duration\n"
    "---|---|---|---|---\n"
    "Record & submit hackathon demo video | Hackathon | Today, 9:00 PM | High | 4h\n"
    "Finalize Devpost submission | Hackathon | Today, 10:00 PM | High | 2h\n"
    "Computer Architecture Lab 5 submission | Coursework | Tomorrow, 11:59 PM | High | 3h\n"
    "DBMS assignment 3 | Coursework | Tomorrow | Medium | 2h\n"
    "Theory of Computation quiz prep | Coursework | Day after tomorrow | Medium | 2h\n"
)


@pytest.mark.parametrize("message", [
    "can you add deadlines for me?",
    "Can you add deadlines for me",
    "do you support adding deadlines?",
    "could you create a task for me?",
    "can I add a reminder?",
])
def test_capability_questions_are_blocked_and_never_a_mutation(message):
    assert classify_task_message(message) == QUESTION
    assert blocks_task_creation(message)
    assert not is_task_mutation_request(message)
    assert is_capability_question(message)
    assert _extract_task_creation_args(message)["title"] == ""


@pytest.mark.parametrize("message, title", [
    ("can you add a task to buy milk tomorrow?", "Buy milk"),
    ("could you remind me to call mom?", "Call mom"),
    ("please add task submit report tomorrow 5pm", "Submit report"),
])
def test_polite_requests_with_a_concrete_task_still_run(message, title):
    assert not blocks_task_creation(message)
    assert _extract_task_creation_args(message)["title"] == title


@pytest.mark.parametrize("message, title", [
    ("add task buy milk tomorrow 5pm", "Buy milk"),
    ("add a deadline on 10th October at 23:59 named Complete Python Programming", "Complete Python Programming"),
    ("remind me to finish Python by October 10", "finish Python"),
])
def test_real_commands_extract_the_task_name_without_word_stripping(message, title):
    assert classify_task_message(message) == STATEMENT
    assert is_task_mutation_request(message) or "remind me to" in message
    assert _extract_task_creation_args(message)["title"] == title


@pytest.mark.parametrize("message", [
    "add deadlines for me", "add a task", "add a deadline", "create a task for tomorrow", "please add a reminder",
])
def test_commands_without_a_task_name_get_no_title(message):
    assert _extract_task_creation_args(message)["title"] == ""


@pytest.mark.parametrize("title", [
    "", "   ", "Can you deadlines for me", "what should I do?", "deadlines", "for me", "123", "a" * 201,
])
def test_title_problem_rejects_unusable_titles(title):
    assert title_problem(title) is not None


@pytest.mark.parametrize("title", ["x", "Buy milk", "Do it by Friday", "Do this assignment", "DBMS assignment 3", "Record & submit demo video"])
def test_title_problem_accepts_meaningful_titles(title):
    assert title_problem(title) is None


def test_classify_statement_vs_command_vs_question():
    assert classify_task_message("buy milk tomorrow") == STATEMENT
    assert classify_task_message("can you add task buy milk?") == COMMAND
    assert classify_task_message("should I buy milk?") == QUESTION


def test_table_paste_parses_every_row_with_fields():
    parsed = parse_task_list(PASTE)
    assert parsed is not None and len(parsed.items) == 5 and not parsed.skipped and not parsed.truncated
    first, third, fourth = parsed.items[0], parsed.items[2], parsed.items[3]
    assert (first.title, first.domain, first.priority, first.duration_minutes, first.due_text) == (
        "Record & submit hackathon demo video", "hackathon", "high", 240, "Today, 9:00 PM")
    assert (third.domain, third.duration_minutes) == ("coursework", 180)
    assert (fourth.priority, fourth.due_text) == ("medium", "Tomorrow")


def test_table_without_header_and_fractional_duration():
    parsed = parse_task_list("add these tasks\nWrite report | Coursework | In 4 days | Low | 1.5h\nFix bug | Code | Tomorrow | High | 30m")
    assert parsed is not None
    assert [i.duration_minutes for i in parsed.items] == [90, 30]
    assert [i.domain for i in parsed.items] == ["coursework", "code"]


def test_rows_without_a_usable_title_are_reported_not_dropped():
    parsed = parse_task_list("Title | Due\nBuy milk | Tomorrow\n? | Friday\nCall mom | Friday")
    assert parsed is not None
    assert [i.title for i in parsed.items] == ["Buy milk", "Call mom"]
    assert len(parsed.skipped) == 1


def test_more_than_the_cap_is_truncated_and_flagged():
    rows = "\n".join(f"Task number {n} | General | Tomorrow | Low | 1h" for n in range(25))
    parsed = parse_task_list("Title | Domain | Due | Priority | Duration\n" + rows)
    assert parsed is not None
    assert len(parsed.items) == MAX_ITEMS and parsed.total_found == 25 and parsed.truncated


def test_bulleted_list_needs_task_intent_and_splits_the_due_text():
    parsed = parse_task_list("Add these tasks:\n- Work on report - tomorrow\n- Buy eggs, milk by Friday\n- Call mom")
    assert parsed is not None
    assert [(i.title, i.due_text) for i in parsed.items] == [
        ("Work on report", "tomorrow"), ("Buy eggs, milk", "Friday"), ("Call mom", ""),
    ]
    assert parse_task_list("Here is my day:\n- gym\n- lunch") is None


@pytest.mark.parametrize("message", ["Buy milk", "add task buy milk", "a | b", "Title | Due\nBuy milk | Tomorrow"])
def test_ordinary_messages_and_single_rows_are_not_lists(message):
    assert parse_task_list(message) is None


@pytest.mark.parametrize("message", [
    "explain this\nls | grep foo\ncat a | wc -l",
    "Summarize these deadlines:\n1. Lab report\n2. Quiz prep",
    "name\tvalue\nfoo\tbar\nbaz\tqux",
])
def test_ordinary_pipe_tab_and_numbered_text_is_not_a_task_list(message):
    assert parse_task_list(message) is None
    assert not is_intake_intent(message)


def test_headerless_table_needs_an_add_request():
    rows = "Write report | Coursework | Tomorrow | High | 2h\nFix bug | Code | Friday | Low | 1h"
    assert parse_task_list(rows) is None
    assert len(parse_task_list("add these tasks:\n" + rows).items) == 2


def test_is_intake_intent_covers_lists_and_capability_questions():
    assert is_intake_intent(PASTE)
    assert is_intake_intent("can you add deadlines for me?")
    assert not is_intake_intent("add task buy milk tomorrow 5pm")


def test_timezone_validation_and_fallback_order():
    assert is_valid_timezone("Asia/Calcutta") and is_valid_timezone("UTC")
    assert not is_valid_timezone("Mars/Phobos") and not is_valid_timezone("../etc/passwd") and not is_valid_timezone(None)
    assert pick_timezone("Asia/Calcutta", "America/New_York") == "Asia/Calcutta"
    assert pick_timezone("Mars/Phobos", "America/New_York") == "America/New_York"
    assert pick_timezone("Mars/Phobos", "also/bad") == "UTC"
    assert pick_timezone(None, None) == "UTC"


def test_local_today_follows_the_users_calendar_day():
    late_utc = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)  # 01:30 on Oct 30 in IST
    assert local_today("Asia/Calcutta", late_utc).isoformat() == "2026-10-30"
    assert local_today("UTC", late_utc).isoformat() == "2026-10-29"


def test_resolve_due_converts_local_time_to_utc():
    now = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
    today_9pm = resolve_due("Today, 9:00 PM", "Asia/Calcutta", now)
    assert today_9pm.due_at == datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc)
    assert today_9pm.label == "Thu Oct 29, 9:00 PM (Asia/Calcutta)"
    assert resolve_due("Today, 9:00 PM", "UTC", now).due_at == datetime(2026, 10, 29, 21, 0, tzinfo=timezone.utc)
    assert resolve_due("Tomorrow, 11:59 PM", "Asia/Calcutta", now).due_at == datetime(2026, 10, 30, 18, 29, tzinfo=timezone.utc)
    assert resolve_due("In 4 days", "UTC", now).due_date.isoformat() == "2026-11-02"


def test_resolve_due_does_not_guess():
    now = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
    assert resolve_due("", "UTC", now).label == "no due date"
    unreadable = resolve_due("whenever", "UTC", now)
    assert unreadable.due_date is None and unreadable.unparsed_text == "whenever"
    date_only = resolve_due("Tomorrow", "Asia/Calcutta", now)
    assert date_only.due_date.isoformat() == "2026-10-30" and date_only.due_at is None


def test_extract_clock_prefers_the_due_string_then_hint_then_message():
    assert extract_clock("2026-10-29 21:00", None, "").hour == 21
    assert extract_clock("2026-10-29", "9:00 PM", "").hour == 21
    assert extract_clock("2026-10-29", None, "add task x tomorrow 5pm").hour == 17
    assert extract_clock("2026-10-29", None, "add task x tomorrow") is None
