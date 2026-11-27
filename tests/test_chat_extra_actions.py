"""Chat extra actions: watchlist add, delete current chat, calendar export instructions.

No database, no network. Pool and memory functions are replaced with fakes.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import router_helpers
from backend.services import chat_extra_actions as cea
from backend.services.chat_task_actions import parse_task_action_intent

OWNER = "user-1"
CONV = "conv-1"


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = lambda: _Acquire(conn)
    return pool


def _opp(opp_id, company, role):
    return {"id": opp_id, "company_name": company, "role_title": role}


@pytest.fixture
def env(monkeypatch):
    """Patch every external dependency of the extra-actions service."""
    mocks = {
        "create": AsyncMock(side_effect=lambda *a, **kw: {"id": 77, "action": kw.get("action")}),
        "active": AsyncMock(return_value=None),
        "resolve": AsyncMock(return_value=True),
        "search": AsyncMock(return_value=([], 0)),
        "get_opp": AsyncMock(return_value={"id": 11}),
        "save": AsyncMock(return_value=True),
        "access": AsyncMock(return_value=(True, None)),
        "delete": AsyncMock(return_value=True),
    }
    monkeypatch.setattr(cea, "create_chat_pending_action", mocks["create"])
    monkeypatch.setattr(cea, "get_active_chat_pending_action", mocks["active"])
    monkeypatch.setattr(cea, "resolve_chat_pending_action", mocks["resolve"])
    monkeypatch.setattr(cea, "get_all_opportunities", mocks["search"])
    monkeypatch.setattr(cea, "get_opportunity_by_id", mocks["get_opp"])
    monkeypatch.setattr(cea, "upsert_user_saved_opportunity", mocks["save"])
    monkeypatch.setattr(cea.conversations, "get_or_create_conversation", AsyncMock(return_value=CONV))
    monkeypatch.setattr(cea.conversations, "add_message", AsyncMock())
    monkeypatch.setattr(cea.conversations, "check_conversation_access", mocks["access"])
    monkeypatch.setattr(cea.conversations, "delete_conversation", mocks["delete"])
    mocks["pool"] = _fake_pool(MagicMock())
    return mocks


async def _run(env, message):
    return await cea.handle_chat_extra_actions_stream(message, CONV, OWNER, None, env["pool"])


# --- Intent parsing ---------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Add Paytm Talent Acquisition Intern to my watchlist",
    "save the Rubrik winter intern to my watchlist",
    "watchlist Rubrik product intern",
])
def test_watchlist_intents_match(message):
    result = cea.parse_extra_action_intent(message)
    assert result is not None, message
    assert result["action"] == "watchlist"
    assert result["target"].strip()


@pytest.mark.parametrize("message", [
    "Add a task to buy milk",
    "my watchlist",
    "what is a watchlist",
])
def test_watchlist_non_intents(message):
    assert cea.parse_extra_action_intent(message) is None, message


@pytest.mark.parametrize("message", ["Delete this chat", "delete this conversation"])
def test_delete_chat_intents_match(message):
    result = cea.parse_extra_action_intent(message)
    assert result == {"action": "delete_chat"}, message


def test_delete_task_is_not_delete_chat():
    result = cea.parse_extra_action_intent("Delete the task buy milk")
    assert result is None or result.get("action") != "delete_chat"


# --- Watchlist flow ---------------------------------------------------------

async def test_watchlist_no_match_is_honest_and_creates_no_pending(env):
    env["search"].return_value = ([_opp(1, "Zebra Corp", "Xylophone Tuner")], 1)
    result = await _run(env, "Add Paytm Talent Acquisition Intern to my watchlist")
    assert result is not None
    assert "couldn't find" in result["response"].lower()
    assert "Done" not in result["response"]
    env["create"].assert_not_called()
    env["save"].assert_not_called()


async def test_watchlist_empty_search_is_honest_and_creates_no_pending(env):
    result = await _run(env, "Add Paytm Talent Acquisition Intern to my watchlist")
    assert "couldn't find" in result["response"].lower()
    env["create"].assert_not_called()
    env["save"].assert_not_called()


async def test_watchlist_single_match_creates_confirm_card_without_saving(env):
    env["search"].return_value = ([_opp(11, "Paytm", "Talent Acquisition Intern"), _opp(2, "Zebra Corp", "Xylophone Tuner")], 2)
    result = await _run(env, "Add Paytm Talent Acquisition Intern to my watchlist")
    assert result is not None
    env["create"].assert_awaited_once()
    kwargs = env["create"].await_args.kwargs
    assert kwargs["action"] == "add_to_watchlist"
    assert kwargs["task_ids"] == [11]
    pending = result["data"]["pending_action"]
    assert "Paytm" in pending["card_text"]
    assert "confirm" in result["response"].lower() and "cancel" in result["response"].lower()
    env["save"].assert_not_called()


async def test_watchlist_confirm_saves_once_and_reports_done(env):
    env["active"].return_value = {
        "id": 77, "action": "add_to_watchlist", "task_ids": [11],
        "task_titles": [_opp(11, "Paytm", "Talent Acquisition Intern")], "conversation_id": CONV,
    }
    result = await _run(env, "Confirm")
    assert result["success"] is True
    assert result["response"].startswith("Done")
    env["save"].assert_awaited_once()
    assert env["save"].await_args.args[1] == 11 or env["save"].await_args.kwargs.get("opportunity_id") == 11


async def test_watchlist_confirm_save_failure_is_honest(env):
    env["save"].side_effect = RuntimeError("db down")
    env["active"].return_value = {
        "id": 77, "action": "add_to_watchlist", "task_ids": [11],
        "task_titles": [_opp(11, "Paytm", "Talent Acquisition Intern")], "conversation_id": CONV,
    }
    result = await _run(env, "Confirm")
    assert result["success"] is False
    assert "Done" not in result["response"]
    assert "couldn't" in result["response"].lower()


async def test_watchlist_several_matches_disambiguate_without_internal_ids(env):
    env["search"].return_value = ([
        _opp(21, "Paytm", "Talent Acquisition Intern"),
        _opp(22, "Paytm", "Product Intern"),
    ], 2)
    result = await _run(env, "Add Paytm intern to my watchlist")
    assert result is not None
    assert env["create"].await_args.kwargs["action"] == "add_to_watchlist_disambiguation"
    pending = result["data"]["pending_action"]
    assert "(ID:" not in result["response"]
    assert "(ID:" not in pending["card_text"]
    env["save"].assert_not_called()


# --- Delete chat flow -------------------------------------------------------

async def test_delete_chat_creates_card_and_does_not_delete_before_confirm(env):
    result = await _run(env, "Delete this chat")
    assert result is not None
    assert env["create"].await_args.kwargs["action"] == "delete_chat"
    assert result["data"]["pending_action"]["card_text"]
    env["delete"].assert_not_called()


async def test_delete_chat_confirm_deletes_once_with_ownership_check(env):
    env["active"].return_value = {
        "id": 77, "action": "delete_chat", "task_ids": [],
        "task_titles": [{"conversation_id": CONV}], "conversation_id": CONV,
    }
    result = await _run(env, "Confirm")
    assert result["data"]["conversation_deleted"] is True
    env["access"].assert_awaited_once()
    assert env["access"].await_args.kwargs.get("user_id") == OWNER
    env["delete"].assert_awaited_once()
    assert env["delete"].await_args.args[1] == CONV


async def test_delete_chat_denied_access_does_not_delete(env):
    env["access"].return_value = (False, "not your conversation")
    env["active"].return_value = {
        "id": 77, "action": "delete_chat", "task_ids": [],
        "task_titles": [{"conversation_id": CONV}], "conversation_id": CONV,
    }
    result = await _run(env, "Confirm")
    assert result["success"] is False
    env["delete"].assert_not_called()


# --- Calendar export --------------------------------------------------------

@pytest.mark.parametrize("message", ["Export my calendar", "download the schedule"])
async def test_export_gives_instruction_and_never_claims_done(env, message):
    result = await _run(env, message)
    assert result is not None
    text = result["response"]
    assert "calendar" in text.lower() and "export" in text.lower()
    for banned in ("exported", "sent", "created"):
        assert banned not in text.lower()


# --- Bounded regex ----------------------------------------------------------

@pytest.mark.parametrize("prefix", ["", "add ", "watchlist ", "delete this "])
def test_parsers_bounded_on_huge_whitespace(prefix):
    message = prefix + " " * 50000
    parsers = [
        cea.parse_extra_action_intent,
        parse_task_action_intent,
        router_helpers.is_chat_delete_intent,
    ]
    for parser in parsers:
        start = time.perf_counter()
        parser(message)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"{parser.__name__} took {elapsed:.2f}s"
