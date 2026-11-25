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


# --- Regression tests: positional replies and task-creation sentences must not parse as task actions ---

@pytest.mark.parametrize("message", [
    "1",
    "first one",
    "the first one",
    "delete the first one",
    "complete the first one",
    "it",
    "that one",
    "the last task",
    "everything",
    "2nd one",
    "mark the first one as done",
    "move the second one to Friday",
])
def test_positional_and_pronoun_replies_are_not_task_actions(message):
    assert parse_task_action_intent(message) is None, message


@pytest.mark.parametrize("message", [
    "remind me to submit my lab report by next Wednesday",
    "add task",
    "add task finish OS assignment by Friday",
    "create a task to move the server to AWS",
    "schedule a meeting with my mentor on Friday",
    "set a reminder for the quiz on Monday",
])
def test_task_creation_sentences_are_not_task_actions(message):
    assert parse_task_action_intent(message) is None, message


@pytest.mark.parametrize("message,action,target_word", [
    ("Mark the Operating Systems assignment as done", "complete", "operating systems"),
    ("I've completed the hackathon proposal", "complete", "hackathon"),
    ("I\u2019ve finished the DBMS lab", "complete", "dbms"),
    ("Change the due date of the Hackathon project proposal to December 5", "reschedule", "hackathon"),
    ("move the DBMS lab to Friday", "reschedule", "dbms"),
])
def test_real_task_actions_still_parse(message, action, target_word):
    result = parse_task_action_intent(message)
    assert result is not None, message
    assert result["action"] == action
    assert target_word in result["target"].lower()


def test_orchestrator_chat_task_action_route_respects_explicit_route_and_pending_action():
    """Source guard: the chat_task_action routing condition must not override an explicit pre_routed_skill."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "backend" / "orchestrator.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    first = next(i for i, line in enumerate(lines) if "chat_task_action" in line)
    window = "\n".join(lines[max(0, first - 12):first + 1])
    assert "pre_routed_skill" in window, window
    assert "pending" in window.lower(), window
