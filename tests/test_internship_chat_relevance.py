"""Chat internship relevance, watchlist name matching and planning-days persistence."""
from datetime import datetime, timezone

import pytest

from backend.models_radar import OpportunityOut, OpportunityStatus
from backend.routers import radar as radar_router
from backend.services import chat_preferences
from backend.services.chat_extra_actions import match_opportunities
from backend.skills.handlers import radar as radar_handler
from backend.skills.handlers.radar import (
    handle_query_internship_radar,
    parse_internship_query,
    rank_internships,
    score_internship,
)

SAMPLE = "Find internships for a 3rd-year B.Tech CSE student in India interested in ML"


def make(idx, company, role, category=None, description=None, fresh=True, location="Bengaluru"):
    return OpportunityOut(
        id=idx,
        company_name=company,
        normalized_company=company.lower(),
        role_title=role,
        category=category,
        description=description,
        location=location,
        official_application_url=f"https://example.com/apply/{idx}",
        canonical_url=f"https://example.com/{idx}",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        last_verified_at=datetime.now(timezone.utc) if fresh else None,
    )


@pytest.fixture
def install(monkeypatch):
    def _install(items):
        async def fake_profile(*_a, **_k):
            return None

        async def fake_recommended(*_a, **_k):
            return list(items)

        monkeypatch.setattr(radar_handler, "get_user_opportunity_profile", fake_profile)
        monkeypatch.setattr(radar_router, "recommended_for_user", fake_recommended)

    return _install


def test_parse_internship_query_sample():
    p = parse_internship_query(SAMPLE)
    assert p["year"] == 3
    assert p["branch"] == "cse"
    assert p["interests"] == ["ai_ml"]
    assert p["location"] == "india"
    assert p["remote"] is False


def test_parse_internship_query_extras():
    p = parse_internship_query("remote 6 months web internship in Pune, stipend 20,000, final year IT")
    assert p["remote"] is True
    assert p["duration_months"] == 6
    assert p["stipend"] == "20000"
    assert p["location"] == "pune"
    assert p["year"] == 4
    assert p["branch"] == "it"
    assert "web" in p["interests"]


def test_parse_internship_query_empty():
    assert parse_internship_query("")["interests"] == []
    assert parse_internship_query(None)["year"] is None


def test_scoring_ml_engineering_above_payroll():
    parsed = parse_internship_query(SAMPLE)
    ml = make(1, "Acme", "Machine Learning Engineer Intern", "ai_ml")
    hr = make(2, "Rubrik", "Payroll Industrial Trainee", "general")
    assert score_internship(ml, parsed)["score"] > score_internship(hr, parsed)["score"]
    relevant, _ = rank_internships([hr, ml], parsed, SAMPLE)
    assert [o.id for o in relevant] == [1]


@pytest.mark.asyncio
async def test_handler_returns_up_to_eight(install):
    items = [make(i, f"Co{i}", f"ML Engineer Intern {i}", "ai_ml") for i in range(1, 13)]
    items.append(make(99, "Rubrik", "Payroll Industrial Trainee"))
    install(items)
    res = await handle_query_internship_radar({"query": SAMPLE})
    assert res["data"]["count"] == 8
    assert "Rubrik" not in res["summary"]
    assert "Apply: https://example.com/apply/" in res["summary"]
    assert "verified today" in res["summary"]


@pytest.mark.asyncio
async def test_handler_honest_when_only_irrelevant(install):
    install([
        make(1, "Rubrik", "Payroll Industrial Trainee"),
        make(2, "Acme", "Talent Acquisition Intern"),
    ])
    res = await handle_query_internship_radar({"query": SAMPLE})
    assert "I found only 0 listings that match" in res["summary"]
    assert "widen" in res["summary"].lower()
    assert "Rubrik" not in res["summary"]
    assert res["data"]["count"] == 0


@pytest.mark.asyncio
async def test_handler_found_only_two_shows_closest(install):
    install([
        make(1, "Acme", "ML Intern", "ai_ml", fresh=False),
        make(2, "Globex", "NLP Research Intern", "ai_ml"),
        make(3, "Rubrik", "Payroll Industrial Trainee"),
    ])
    res = await handle_query_internship_radar({"query": SAMPLE})
    assert "I found only 2 listings that match; here is the closest" in res["summary"]
    assert "needs re-check" in res["summary"]
    assert "Rubrik" not in res["summary"]


# ---- watchlist ----

PAYTM = {"id": 1, "company_name": "Paytm", "role_title": "Talent Acquisition Intern"}
AURORA = {"id": 2, "company_name": "Aurora", "role_title": "LiDAR Engineer Intern"}


def test_watchlist_no_match_returns_empty():
    assert match_opportunities("Google STEP", [PAYTM, AURORA]) == []


def test_watchlist_exact_company_matches():
    res = match_opportunities("Aurora", [PAYTM, AURORA])
    assert [r["id"] for r in res] == [2]


def test_watchlist_all_tokens_match():
    res = match_opportunities("Paytm Talent Acquisition", [PAYTM, AURORA])
    assert [r["id"] for r in res] == [1]


@pytest.mark.asyncio
async def test_watchlist_reply_has_no_suggestions(monkeypatch):
    from backend.services import chat_extra_actions as cea

    async def fake_all(**_k):
        return [PAYTM, AURORA], 2

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    async def noop(*_a, **_k):
        return "cid"

    async def no_pending(*_a, **_k):
        return None

    monkeypatch.setattr(cea, "get_active_chat_pending_action", no_pending)
    monkeypatch.setattr(cea, "get_all_opportunities", fake_all)
    monkeypatch.setattr(cea.conversations, "get_or_create_conversation", noop)
    monkeypatch.setattr(cea.conversations, "add_message", noop)
    out = await cea.handle_chat_extra_actions_stream("Add Google STEP to watchlist", "c1", "u1", None, _Pool())
    msg = out["response"]
    assert msg == (
        'I couldn\'t find a listing called "Google STEP" in Open Now. '
        "Try the exact company or role from the Radar, or search it there."
    )
    assert "Paytm" not in msg and "Aurora" not in msg


# ---- planning days ----

def test_parser_mon_to_sat():
    p = chat_preferences.parse_preferences_intent("Change work hours 10 to 7 and working days Monday to Saturday")
    assert p["work_days"] == [1, 2, 3, 4, 5, 6]
    assert (p["work_start_time"], p["work_end_time"]) == ("10:00", "19:00")
    assert "Mon-Sat" in chat_preferences.format_pref_card_text(p)


class FakeConn:
    def __init__(self, persist_days=True):
        self.calls = []
        self.persist_days = persist_days
        self.row = {
            "user_id": "u1", "work_start_time": "09:00:00", "work_end_time": "18:00:00",
            "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15, "preferred_focus": "morning",
        }

    async def execute(self, query, *args):
        self.calls.append(args)
        if "UPDATE scheduling_preferences" in query:
            _, s_flag, s, e_flag, e, d_flag, d, *_ = args
            if s_flag:
                self.row["work_start_time"] = s.strftime("%H:%M:%S")
            if e_flag:
                self.row["work_end_time"] = e.strftime("%H:%M:%S")
            if d_flag and self.persist_days:
                self.row["work_days"] = d

    async def fetchrow(self, *_a):
        return dict(self.row)


async def _run(monkeypatch, conn):
    async def claimed(*_a, **_k):
        return True

    monkeypatch.setattr(chat_preferences, "resolve_chat_pending_action", claimed)
    pref = chat_preferences.parse_preferences_intent("Change work hours 10 to 7 and working days Monday to Saturday")
    action = {"id": 1, "task_titles": [dict(pref)]}
    return await chat_preferences.execute_pending_preferences(conn, action, "u1", "confirm")


@pytest.mark.asyncio
async def test_preferences_save_work_days_and_read_back(monkeypatch):
    conn = FakeConn()
    msg, data, ok = await _run(monkeypatch, conn)
    update_args = conn.calls[-1]
    assert update_args[5] is True and update_args[6] == [1, 2, 3, 4, 5, 6]
    assert ok is True
    assert "10:00-19:00" in msg and "Mon-Sat" in msg
    assert data["preferences"]["work_days"] == [1, 2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_preferences_reports_unsaved_working_days(monkeypatch):
    conn = FakeConn(persist_days=False)
    msg, _data, ok = await _run(monkeypatch, conn)
    assert ok is False
    assert msg == "I could not save the working days; hours were saved."
    assert "Done" not in msg
