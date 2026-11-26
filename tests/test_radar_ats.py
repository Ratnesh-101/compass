"""Public ATS adapters (Greenhouse, Lever, Ashby) for India internships. No network, no database."""
from __future__ import annotations

import re

import pytest

from backend.models_radar import OpportunityStatus
from backend.services.radar_ats import _TITLE_INTERN_RE, parse_ashby, parse_greenhouse, parse_lever
from backend.services.radar_ats_companies import ATS_COMPANIES

GH_URL = "https://boards.greenhouse.io/acme/jobs/1"
LV_URL = "https://jobs.lever.co/acme/abc-1"
AS_URL = "https://jobs.ashbyhq.com/acme/abc-1"


def _gh(title, location):
    return {"jobs": [{"id": 1, "title": title, "location": {"name": location}, "absolute_url": GH_URL}]}


def _lv(title, location):
    return [{"id": "abc-1", "text": title, "categories": {"location": location}, "hostedUrl": LV_URL}]


def _as(title, location):
    return {"jobs": [{"id": "abc-1", "title": title, "location": location, "jobUrl": AS_URL}]}


CASES = [
    ("greenhouse", parse_greenhouse, _gh, GH_URL),
    ("lever", parse_lever, _lv, LV_URL),
    ("ashby", parse_ashby, _as, AS_URL),
]


@pytest.mark.parametrize("name,parse,build,url", CASES)
def test_india_intern_is_kept(name, parse, build, url):
    out = parse(build("Software Engineer Intern", "Bengaluru, India"), "Acme")
    assert len(out) == 1
    opp = out[0]
    assert opp["company_name"] == "Acme"
    assert opp["role_title"] == "Software Engineer Intern"
    assert opp["official_application_url"] == url
    assert opp["is_india_eligible"] is True
    assert opp["current_status"] == OpportunityStatus.OPEN_CONFIRMED


@pytest.mark.parametrize("name,parse,build,url", CASES)
def test_us_intern_is_dropped(name, parse, build, url):
    assert parse(build("Software Engineer Intern", "San Francisco, CA"), "Acme") == []


@pytest.mark.parametrize("name,parse,build,url", CASES)
def test_non_intern_india_posting_is_dropped(name, parse, build, url):
    assert parse(build("Senior Software Engineer", "Bengaluru, India"), "Acme") == []


@pytest.mark.parametrize("name,parse,build,url", CASES)
@pytest.mark.parametrize("title", ["International Sales Manager", "Internal Tools Engineer"])
def test_lookalike_titles_are_not_interns(name, parse, build, url, title):
    assert parse(build(title, "Bengaluru, India"), "Acme") == []


@pytest.mark.parametrize("title", ["International Sales Manager", "Internal Tools Engineer"])
def test_title_regex_is_whole_word(title):
    assert _TITLE_INTERN_RE.search(title) is None


@pytest.mark.parametrize("name,parse,build,url", CASES)
@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {},
        {"jobs": "x"},
        {"postings": "x"},
        "garbage",
        42,
        {"jobs": [None, 1, "x", [], {}]},
        {"jobs": [{"title": None, "location": None}]},
        {"jobs": [{"title": 5, "location": 7, "text": 5, "categories": "x"}]},
        {"jobs": [{"title": "Data Intern", "location": {"name": "India"}}]},
        [None, 1, "x", {"text": "Data Intern", "categories": 3}],
    ],
)
def test_garbage_payloads_return_empty(name, parse, build, url, payload):
    assert parse(payload, "Acme") == []


def test_company_list_shape():
    keys = [(p, s) for p, s, *_ in ATS_COMPANIES]
    assert len(set(keys)) == len(keys)
    assert len(keys) <= 60
    for provider, slug, *_ in ATS_COMPANIES:
        assert provider in {"greenhouse", "lever", "ashby"}
        assert re.fullmatch(r"[a-z0-9-]+", slug)
