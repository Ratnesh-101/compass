"""Unit tests for chat task actions: complete/reschedule intent parsing and open-task matching (no database)."""

import pytest

from backend.services.chat_task_actions import match_open_task, parse_task_action_intent

LEADING_VERBS = {
    "mark", "complete", "finished", "finish", "tick", "move", "push", "reschedule",
    "postpone", "change", "set", "i", "i've", "ive",
}


@pytest.mark.parametrize("message", [
    "Mark the Operating Systems assignment as done",
    "mark OS assignment as complete",
    "I finished the DBMS lab",
    "I've completed the hackathon proposal",
    "complete buy groceries",
    "tick off the quiz",
    "the compiler quiz is done",
])
def test_complete_intents(message):
    result = parse_task_action_intent(message)
    assert result is not None, message
    assert result["action"] == "complete"
    assert isinstance(result["target"], str) and result["target"].strip()
    assert result["target"].strip().split()[0].lower() not in LEADING_VERBS
    assert result.get("new_due") is None


@pytest.mark.parametrize("message", [
    "Change the due date of the Hackathon project proposal to December 5",
    "move the DBMS lab to Friday",
    "push the OS assignment to next Wednesday",
    "reschedule the quiz to tomorrow 6pm",
    "set the resume task due 2026-12-05",
    "postpone the hackathon proposal to Dec 10",
])
def test_reschedule_intents(message):
    result = parse_task_action_intent(message)
    assert result is not None, message
    assert result["action"] == "reschedule"
    assert isinstance(result["target"], str) and result["target"].strip()
    assert result["target"].strip().split()[0].lower() not in LEADING_VERBS
    assert isinstance(result["new_due"], str) and result["new_due"].strip()


@pytest.mark.parametrize("message,target_word,due_word", [
    ("move the DBMS lab to Friday", "dbms", "friday"),
    ("postpone the hackathon proposal to Dec 10", "hackathon", "dec"),
    ("set the resume task due 2026-12-05", "resume", "2026-12-05"),
    ("reschedule the quiz to tomorrow 6pm", "quiz", "tomorrow"),
])
def test_reschedule_splits_target_and_due(message, target_word, due_word):
    result = parse_task_action_intent(message)
    assert result is not None
    assert target_word in result["target"].lower()
    assert due_word in result["new_due"].lower()
    assert due_word not in result["target"].lower()


@pytest.mark.parametrize("message", [
    "What should I mark as done first?",
    "Which tasks are done?",
    "How do I move a task?",
    "I'll mark it later maybe?",
    "Can you explain what a due date is",
    "delete the OS assignment",
    "add a task to finish the OS assignment",
    "plan my week",
    "hello",
])
def test_non_intents_return_none(message):
    assert parse_task_action_intent(message) is None


TASKS = [
    {"id": 1, "title": "Operating Systems assignment"},
    {"id": 2, "title": "DBMS lab report"},
    {"id": 3, "title": "Hackathon project proposal"},
    {"id": 4, "title": "Compiler quiz"},
    {"id": 5, "title": "Physics assignment"},
]


def test_exact_title_returns_only_that_task():
    result = match_open_task("Operating Systems assignment", TASKS)
    assert [t["id"] for t in result] == [1]


def test_typo_still_ranks_right_task_first():
    result = match_open_task("operating sytems assignment", TASKS)
    assert result and result[0]["id"] == 1


def test_ambiguous_word_returns_all_candidates():
    result = match_open_task("assignment", TASKS)
    assert len(result) >= 2
    assert {1, 5} <= {t["id"] for t in result}


def test_no_match_returns_empty():
    assert match_open_task("zebra migration xylophone", TASKS) == []


def test_results_capped_at_five():
    many = [{"id": i, "title": f"Assignment {i}"} for i in range(1, 10)]
    result = match_open_task("assignment", many)
    assert 2 <= len(result) <= 5


@pytest.mark.parametrize("target", [
    "COMPILER QUIZ",
    "the compiler quiz",
    "compiler quiz task",
    "the Compiler Quiz task",
])
def test_case_and_filler_words_are_ignored(target):
    result = match_open_task(target, TASKS)
    assert [t["id"] for t in result] == [4]
