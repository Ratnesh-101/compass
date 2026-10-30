from backend.agent_confirm_nudge import (
    MAX_NUDGES,
    NUDGE_MESSAGE,
    reply_asks_for_permission,
    should_nudge_for_tool_call,
)

MUTATING = frozenset({"add_task", "edit_task", "delete_task"})

CONFIRM_TEXT = (
    "I can move the coursework deadlines to free up time. Would you like me to go ahead "
    "and update the due dates for the first two tasks to Nov 2, 2026? Please confirm "
    "or let me know if you'd prefer different new dates or any other changes."
)


def test_reply_asks_for_permission_true_for_confirmation_request():
    assert reply_asks_for_permission(CONFIRM_TEXT) is True


def test_reply_asks_for_permission_false_for_pure_information_offer():
    text = "Here are your open tasks. Would you like me to explain any of them in more detail?"
    assert reply_asks_for_permission(text) is False


def test_reply_asks_for_permission_false_for_plain_answer():
    text = "Your lab is due on Saturday and the quiz is on Sunday."
    assert reply_asks_for_permission(text) is False


def test_reply_asks_for_permission_false_for_empty_string_and_none():
    assert reply_asks_for_permission("") is False
    assert reply_asks_for_permission(None) is False


def test_should_nudge_for_tool_call_true_when_permission_asked_and_no_mutation():
    assert should_nudge_for_tool_call(CONFIRM_TEXT, ["query_tasks"], 0, MUTATING) is True


def test_should_nudge_for_tool_call_false_when_mutating_tool_already_called():
    assert should_nudge_for_tool_call(CONFIRM_TEXT, ["edit_task"], 0, MUTATING) is False
    assert should_nudge_for_tool_call(CONFIRM_TEXT, ["query_tasks", "edit_task"], 0, MUTATING) is False


def test_should_nudge_for_tool_call_false_when_nudges_used_equals_max_nudges():
    assert should_nudge_for_tool_call(CONFIRM_TEXT, ["query_tasks"], MAX_NUDGES, MUTATING) is False


def test_nudge_message_is_non_empty_str_and_contains_directive():
    assert isinstance(NUDGE_MESSAGE, str)
    assert len(NUDGE_MESSAGE) > 0
    assert "Call the appropriate tool" in NUDGE_MESSAGE
