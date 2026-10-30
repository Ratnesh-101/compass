"""Planner task ids, deadline-verification query and clean evidence quotes."""
import time

import pytest

from backend.agent_step_executor import execute_agent_tool_step
from backend.services.deadline_query import build_deadline_query, event_subject
from backend.services.task_id_hint import MAX_HINT_TASKS, task_id_hint
from backend.services.tavily_deadline import extract_dates_from_results, whole_word_window


def test_task_id_hint_maps_titles_to_ids():
    hint = task_id_hint([{"id": 1805, "title": "DBMS assignment 3"}, {"id": 1806, "title": "Quiz prep"}])
    assert "DBMS assignment 3 = 1805" in hint
    assert "Quiz prep = 1806" in hint
    assert "task_id" in hint


@pytest.mark.parametrize("data", [None, "text", {"id": 1}, [], [{"title": "no id"}], [{"id": 1}], [3, "x"]])
def test_task_id_hint_is_empty_when_there_is_nothing_to_map(data):
    assert task_id_hint(data) == ""


def test_task_id_hint_is_capped():
    hint = task_id_hint([{"id": n, "title": f"Task {n}"} for n in range(MAX_HINT_TASKS + 10)])
    assert hint.count(" = ") == MAX_HINT_TASKS


@pytest.mark.asyncio
async def test_agent_tool_message_carries_task_ids_but_the_visible_step_does_not(monkeypatch):
    from backend.skills import SKILL_REGISTRY

    async def fake_query_tasks(args, pool):
        return {"response": "Found 1 task(s):\n- **DBMS assignment 3**", "data": [{"id": 1805, "title": "DBMS assignment 3"}]}

    monkeypatch.setitem(SKILL_REGISTRY, "query_tasks", fake_query_tasks)
    obs_step, tool_result, _, _, tool_payload = await execute_agent_tool_step(
        func_name="query_tasks", tool_args={}, raw_args="{}", tc_id="tc1", step_num=1, step_start=time.perf_counter(),
        run_id="run1", pool=None, user_id="user-1", goal="g", abstain_first=False, search_web_unlocked=True, tools_used=[],
    )

    assert "DBMS assignment 3 = 1805" in tool_payload["content"]
    assert "1805" not in obs_step.content
    assert "1805" not in tool_result


def test_event_subject_prefers_a_real_project_name_and_drops_generic_tail_words():
    assert event_subject("Nebius submission draft", "Nebius x NVIDIA Global AI Hackathon") == "Nebius x NVIDIA Global AI Hackathon"
    assert event_subject("Nebius x NVIDIA Global AI Hackathon submission", "General") == "Nebius x NVIDIA Global AI Hackathon"
    assert event_subject("Final submission deadline", None) == "Final"


def test_hackathon_query_asks_for_the_official_rules_page():
    query = build_deadline_query("Hackathon submission", "Nebius x NVIDIA Global AI Hackathon", "hackathon")
    assert query == "Nebius x NVIDIA Global AI Hackathon Devpost official rules submission period deadline"


def test_non_hackathon_query_has_no_devpost_bias():
    assert build_deadline_query("DBMS assignment 3", "General", "coursework") == "DBMS assignment 3 official deadline date"


def test_whole_word_window_never_leaves_half_words():
    content = "alpha bravo charlie delta echo foxtrot golf"
    start, end = content.index("ravo"), content.index("hotel") if "hotel" in content else content.index("olf")
    assert whole_word_window(content, start, end) == "charlie delta echo foxtrot"


def test_whole_word_window_keeps_edges_that_are_already_word_boundaries():
    content = "alpha bravo charlie delta"
    assert whole_word_window(content, 6, 19) == "bravo charlie"


def test_evidence_snippet_for_a_found_date_has_no_cut_words():
    text = "xx" + "intro " * 20 + "Submission Period: Wednesday, August 26, 2026 to Friday, October 30, 2026 deadline " + "outro " * 20
    results = [{"url": "https://nebiusglobalaihackathon.devpost.com/rules", "title": "Rules", "content": text}]
    snippet = extract_dates_from_results(results)[0]["snippet"]
    words = set(text.split())
    assert snippet and all(token in words for token in snippet.split()), snippet


def test_nudge_messages_replay_the_reply_then_ask_for_the_tool_call():
    from backend.agent_confirm_nudge import NUDGE_MESSAGE, nudge_messages

    assert nudge_messages("Would you like me to update it?") == [
        {"role": "assistant", "content": "Would you like me to update it?"},
        {"role": "user", "content": NUDGE_MESSAGE},
    ]
