"""
Compass - Feasibility: the numbers quoted to the user are the real numbers.  DB-free:
task loading and the model are patched.
"""

import re
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from backend.skills.handlers.feasibility import handle_assess_feasibility
from backend.skills.schemas import BASE_TOOL_DEFINITIONS


class _DummyPool:
    """Never used for queries because _fetch_open_tasks is patched."""


def _task(i: int, title: str, minutes: int, *, priority: str = "high",
          domain: str = "coursework", due: Optional[str] = "2026-12-01") -> Dict[str, Any]:
    return {"id": i, "title": title, "priority": priority, "domain": domain,
            "due_date": due, "duration_minutes": minutes, "status": "open"}


def _patch_tasks(monkeypatch, tasks: List[Dict[str, Any]]) -> None:
    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))


_NINE_TITLES = ["Alpha essay", "Bravo lab", "Charlie quiz", "Delta poster", "Echo viva",
                "Foxtrot slides", "Golf report", "Hotel proof", "India survey"]
_NINE_MINUTES = [240, 200, 180, 180, 170, 160, 150, 160, 150]  # 1590 min = 26.5 h


def _nine_tasks() -> List[Dict[str, Any]]:
    assert sum(_NINE_MINUTES) == 1590
    return [_task(i + 1, t, m) for i, (t, m) in enumerate(zip(_NINE_TITLES, _NINE_MINUTES))]


async def _assess(days: int, hours: float, **extra: Any) -> Dict[str, Any]:
    args = {"user_id": "u1", "days": days, "hours_per_day": hours, "days_stated": True}
    args.update(extra)
    res = await handle_assess_feasibility(args, _DummyPool())
    assert res["success"] is True, res
    return res


def _titles(plan: Dict[str, Any], bucket: str) -> List[str]:
    return [t["title"] for t in plan[bucket]]


# ---------------------------------------------------------------------------
# demand and capacity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("days,hours", [(7, 2.0), (9, 3.0)])
async def test_demand_is_sum_of_task_durations(monkeypatch, days, hours):
    _patch_tasks(monkeypatch, _nine_tasks())
    res = await _assess(days, hours)
    summary = res["summary"]
    assert res["data"]["triage_plan"]["verdict"]["demand_hours"] == 26.5
    assert "26.5" in summary
    # no other demand figure is quoted next to "of work"
    assert not re.search(r"(?<![\d.])(?!26\.5)\d+(?:\.\d+)?h of work", summary), summary


@pytest.mark.asyncio
@pytest.mark.parametrize("days,hours", [(7, 2.0), (9, 3.0)])
async def test_percentage_matches_quoted_capacity(monkeypatch, days, hours):
    _patch_tasks(monkeypatch, _nine_tasks())
    res = await _assess(days, hours)
    summary = res["summary"]
    nominal = days * hours
    # Capacity may be quoted as the nominal figure or as an explicitly described allowance of it.
    candidates = {nominal, round(nominal * 0.8, 2), round(nominal * 0.75, 2), round(nominal * 0.9, 2)}
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", summary)
    assert pct_match, summary
    pct = float(pct_match.group(1))

    def quoted(c: float) -> bool:
        return re.search(rf"(?<![\d.]){re.escape(format(c, 'g'))}\s*(?:h|hours)", summary) is not None

    ok = [c for c in candidates if quoted(c) and abs(26.5 / c * 100 - pct) <= 0.6]
    assert ok, f"percentage {pct} does not equal 26.5 / a quoted capacity in: {summary}"


# ---------------------------------------------------------------------------
# verdict wording
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("days,hours", [(7, 2.0), (9, 3.0)])
async def test_not_all_fits_lists_deferred_and_dropped_titles(monkeypatch, days, hours):
    _patch_tasks(monkeypatch, _nine_tasks())
    res = await _assess(days, hours)
    plan = res["data"]["triage_plan"]
    summary = res["summary"]
    left_out = _titles(plan, "defer") + _titles(plan, "drop")
    assert left_out, "expected some tasks to be deferred or dropped"
    assert "Not all of it fits" in summary
    assert "Yes, it fits" not in summary
    for title in left_out:
        assert title in summary, f"{title!r} missing from: {summary}"


@pytest.mark.asyncio
async def test_small_workload_fits(monkeypatch):
    tasks = [_task(1, "Read chapter", 90), _task(2, "Fix bug", 60), _task(3, "Write notes", 90)]
    _patch_tasks(monkeypatch, tasks)
    res = await _assess(7, 2.0)
    plan = res["data"]["triage_plan"]
    assert plan["verdict"]["demand_hours"] == 4.0
    assert plan["defer"] == [] and plan["drop"] == []
    assert "Yes, it fits" in res["summary"]
    assert "Not all of it fits" not in res["summary"]


# ---------------------------------------------------------------------------
# empty and fallback cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_summary_is_only_the_plain_sentence(monkeypatch):
    _patch_tasks(monkeypatch, [])
    res = await _assess(5, 4.0)
    summary = res["summary"]
    assert summary.startswith("Nothing to assess yet")
    assert "0.0h" not in summary
    assert "Keeping 0" not in summary
    assert "Keeping" not in summary


@pytest.mark.asyncio
async def test_domain_filter_retried_without_filter(monkeypatch):
    tasks = [_task(1, "Lab write-up", 120, domain="coursework"),
             _task(2, "Problem set", 60, domain="coursework")]
    calls: List[Optional[str]] = []

    async def fake_fetch(pool, domain, user_id=None, include_demo=False):
        calls.append(domain)
        return [] if domain else tasks

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", fake_fetch)
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))
    res = await _assess(5, 4.0, domain="general")
    plan = res["data"]["triage_plan"]
    assert plan["keep"] or plan["defer"] or plan["drop"]
    assert "I looked at all your open tasks" in res["summary"]
    assert calls[0] == "general" and None in calls[1:]


# ---------------------------------------------------------------------------
# title lists
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bucket_titles_truncate_after_eight(monkeypatch):
    names = ["Apple", "Birch", "Cedar", "Dahlia", "Elm", "Fern", "Ginkgo", "Hazel",
             "Iris", "Juniper", "Kelp"]
    tasks = [_task(i + 1, f"Topic {n}", 600) for i, n in enumerate(names)]  # 10 h each
    _patch_tasks(monkeypatch, tasks)
    res = await _assess(1, 2.0)
    plan = res["data"]["triage_plan"]
    assert plan["keep"] == []
    assert len(plan["defer"]) == 11
    summary = res["summary"]
    assert "and 3 more" in summary
    assert sum(1 for n in names if f"Topic {n}" in summary) == 8


# ---------------------------------------------------------------------------
# tool schema
# ---------------------------------------------------------------------------
def test_assess_feasibility_schema_has_workload_and_days_stated():
    entry = next(t for t in BASE_TOOL_DEFINITIONS if t["function"]["name"] == "assess_feasibility")
    props = entry["function"]["parameters"]["properties"]
    assert props["workload_hours"]["type"] == "number"
    assert props["days_stated"]["type"] == "boolean"
    assert "workload_hours" not in entry["function"]["parameters"].get("required", [])
    assert "days_stated" not in entry["function"]["parameters"].get("required", [])
