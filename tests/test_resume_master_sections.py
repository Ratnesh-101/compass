"""My resume editor sections: the master-resume save round-trips education, projects, experience and
links, and the application pack reads work authorization / notice period / links from the master."""

import uuid

import pytest
from httpx import AsyncClient

from backend.memory.radar import upsert_opportunity

BODY = {
    "full_name": "Sections Tester",
    "email": "sections@example.com",
    "skills": ["Python"],
    "education": [{
        "institution": "Test University", "degree": "B.Tech", "field_of_study": "CSE",
        "start_year": 2021, "end_year": 2025, "cgpa_or_grade": "8.5",
    }],
    "projects": [{
        "title": "Compass", "description": "Career copilot", "technologies": ["Python", "React"],
        "project_url": "https://example.com/compass",
    }],
    "experience": [{
        "company": "Acme", "role_title": "Intern", "start_date": "Jun 2024", "is_current": True,
        "highlights": ["Built an API"],
    }],
    "linkedin_url": "https://www.linkedin.com/in/tester",
    "github_or_portfolio": "https://github.com/tester",
    "relevant_links": ["https://tester.dev"],
    "evidence_notes": {
        "work_authorization": "Authorised to work in India",
        "notice_period": "Immediately available",
    },
}


async def _headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/guest/session")
    assert resp.status_code == 200
    return {"x-guest-token": resp.json()["guest_token"]}


@pytest.mark.asyncio
async def test_master_save_round_trips_sections(client: AsyncClient):
    headers = await _headers(client)
    put = await client.put("/api/career/resumes/master", headers=headers, json=BODY)
    assert put.status_code == 200
    got = await client.get("/api/career/resumes/master", headers=headers)
    assert got.status_code == 200
    c = got.json()["content"]
    assert c["education"][0]["institution"] == "Test University"
    assert c["education"][0]["start_year"] == 2021
    assert c["education"][0]["cgpa_or_grade"] == "8.5"
    assert c["projects"][0]["title"] == "Compass"
    assert c["projects"][0]["technologies"] == ["Python", "React"]
    assert c["projects"][0]["project_url"] == "https://example.com/compass"
    assert c["experience"][0]["is_current"] is True
    assert c["linkedin_url"] == BODY["linkedin_url"]
    assert c["github_or_portfolio"] == BODY["github_or_portfolio"]
    assert c["relevant_links"] == ["https://tester.dev"]
    assert c["evidence_notes"]["work_authorization"] == "Authorised to work in India"
    assert c["evidence_notes"]["notice_period"] == "Immediately available"


@pytest.mark.asyncio
async def test_application_pack_reads_master_details(client: AsyncClient):
    headers = await _headers(client)
    assert (await client.put("/api/career/resumes/master", headers=headers, json=BODY)).status_code == 200
    opp_id = await upsert_opportunity(
        "Sections Corp", "Backend Intern", f"https://sections.test/careers/{uuid.uuid4().hex}"
    )
    created = await client.post(f"/api/career/applications/{opp_id}", headers=headers)
    assert created.status_code == 200
    kit = await client.get(f"/api/career/applications/{created.json()['id']}/handoff-kit", headers=headers)
    assert kit.status_code == 200
    answers = kit.json()["common_answers"]
    assert answers["work_authorization"] == "Authorised to work in India"
    assert answers["notice_or_availability"] == "Immediately available"
    assert answers["linkedin_url"] == BODY["linkedin_url"]
    assert answers["github_url"] == BODY["github_or_portfolio"]
    assert answers["portfolio_url"] == "https://tester.dev"
    missing = kit.json().get("missing_fields") or []
    for key in ("work_authorization", "notice_or_availability", "linkedin_url", "github_url", "portfolio_url"):
        assert key not in missing
