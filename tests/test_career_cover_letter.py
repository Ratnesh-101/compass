"""Cover letter validator, clean template and the write-validate-regenerate loop (N-006). No network."""
from __future__ import annotations

import pytest

from backend.models_career import ResumeContent, ResumeEducationItem, ResumeProjectItem
from backend.models_radar import OpportunityOut
from backend.services import career_cover_letter as cl


def _opp(**over):
    base = dict(
        id=7,
        company_name="1Password",
        normalized_company="1password",
        role_title="Software Engineer Intern",
        category="swe",
        location="Remote",
        description="Build secure Python and React tools. You will work with a small team on the web client.",
        canonical_url="https://example.com/jobs/7",
        current_status="open_confirmed",
        source="devpost",
    )
    base.update(over)
    return OpportunityOut(**base)


def _master(**over):
    base = dict(
        full_name="Priya Sharma",
        email="priya@example.com",
        phone="+91 98765 43210",
        skills=["Python", "React", "SQL"],
        education=[ResumeEducationItem(institution="Pune Institute of Technology", degree="B.Tech", field_of_study="Computer Science", end_year=2028)],
        projects=[ResumeProjectItem(title="Library Management System", description="Built a web app for the college library.", technologies=["React", "Flask"])],
    )
    base.update(over)
    return ResumeContent(**base)


GOOD_LETTER = (
    "Dear Hiring Team at 1Password,\n\n"
    "I am writing to apply for the Software Engineer Intern position at 1Password. I am studying B.Tech in Computer Science "
    "at Pune Institute of Technology and expect to graduate in 2028. My skills include Python, React and SQL.\n\n"
    "One project I am proud of is Library Management System. I built a web app for the college library using React and Flask. "
    "It taught me how to design a simple data model and keep the interface clear for everyday users.\n\n"
    "I would welcome the chance to discuss how I can contribute to 1Password. Thank you for your time and consideration.\n\n"
    "Sincerely,\nPriya Sharma\npriya@example.com | +91 98765 43210"
)


def test_a_clean_letter_passes():
    assert cl.validate_cover_letter(GOOD_LETTER, full_name="Priya Sharma", company="1Password", source_text="2028 B.Tech") == []


@pytest.mark.parametrize(
    "bad",
    [
        "Dear Hiring Team,\n\nI am [Your Name] and I want this job. " + "x " * 200 + "\n\nSincerely,\nPriya Sharma",
        "Dear Hiring Team at 1Password,\n\nFor example, I built used by 200 students.. " + "word " * 80 + "\n\nSincerely,\nPriya Sharma",
        "Dear Hiring Team at 1Password,\n\nIt was built with React;. " + "word " * 80 + "\n\nSincerely,\nPriya Sharma",
    ],
)
def test_placeholders_and_broken_fragments_are_rejected(bad):
    assert cl.validate_cover_letter(bad, full_name="Priya Sharma", company="1Password")


def test_each_problem_is_named_in_plain_words():
    text = GOOD_LETTER.replace("Priya Sharma\npriya", "Priya\npriya")
    problems = cl.validate_cover_letter(text, full_name="Priya Sharma", company="1Password")
    assert any("not signed with the candidate's name" in p for p in problems)

    assert any("placeholder" in p for p in cl.validate_cover_letter(GOOD_LETTER.replace("1Password.", "[Company].", 1), full_name="Priya Sharma", company="1Password"))
    assert any("stray ';.'" in p for p in cl.validate_cover_letter(GOOD_LETTER.replace("React and Flask.", "React and Flask;."), full_name="Priya Sharma", company="1Password"))
    assert any("double full stop" in p for p in cl.validate_cover_letter(GOOD_LETTER.replace("clear for everyday users.", "clear for everyday users.."), full_name="Priya Sharma", company="1Password"))


def test_figures_not_in_the_profile_are_rejected():
    invented = GOOD_LETTER.replace("a web app", "a web app used by 500 students")
    problems = cl.validate_cover_letter(invented, full_name="Priya Sharma", company="1Password", source_text="2028")
    assert any("500" in p for p in problems)


def test_letter_without_greeting_or_company_or_signature_is_rejected():
    assert cl.validate_cover_letter("", full_name="P", company="X")
    no_greeting = GOOD_LETTER.replace("Dear Hiring Team at 1Password,", "Hello")
    assert any("greeting" in p for p in cl.validate_cover_letter(no_greeting, full_name="Priya Sharma", company="1Password"))
    no_company = GOOD_LETTER.replace("1Password", "the firm")
    assert any("company" in p for p in cl.validate_cover_letter(no_company, full_name="Priya Sharma", company="1Password"))


def test_unfinished_last_paragraph_is_rejected():
    cut = GOOD_LETTER.replace("Thank you for your time and consideration.", "Thank you for your")
    assert any("stops without ending" in p for p in cl.validate_cover_letter(cut, full_name="Priya Sharma", company="1Password"))


def test_safe_template_is_signed_clean_and_uses_only_profile_facts():
    master, opp = _master(), _opp()
    skills = cl.pick_skills(master, opp)
    projects = cl.pick_projects(master, opp)
    letter = cl.build_safe_cover_letter(master, opp, skills, projects)
    assert letter.startswith("Dear Hiring Team at 1Password,")
    assert "Priya Sharma" in letter.splitlines()[-2] or "Priya Sharma" in letter[-120:]
    assert "Pune Institute of Technology" in letter and "2028" in letter
    assert "Library Management System" in letter
    for token in ("[", "]", "{", "}", ";.", ".."):
        assert token not in letter
    assert cl.validate_cover_letter(letter, full_name="Priya Sharma", company="1Password") == []


def test_safe_template_drops_a_fragment_description_instead_of_quoting_it():
    master = _master(projects=[ResumeProjectItem(title="Chat App", description="used by 200..", technologies=[])])
    opp = _opp()
    letter = cl.build_safe_cover_letter(master, opp, cl.pick_skills(master, opp), cl.pick_projects(master, opp))
    assert "Chat App" in letter
    assert "used by 200" not in letter


def test_safe_template_works_with_a_nearly_empty_profile():
    master = ResumeContent(full_name="Priya Sharma", email="priya@example.com")
    letter = cl.build_safe_cover_letter(master, _opp(), [], [])
    assert "Sincerely,\nPriya Sharma" in letter
    assert "None" not in letter and "[" not in letter


def test_model_artifacts_are_removed():
    assert cl.strip_model_artifacts("<think>plan</think>Dear X,\nBody") == "Dear X,\nBody"
    assert cl.strip_model_artifacts("```text\nDear X\n```") == "Dear X"


@pytest.mark.asyncio
async def test_compose_uses_a_valid_model_letter(monkeypatch):
    calls = []

    async def fake(system, user):
        calls.append(user)
        return GOOD_LETTER

    monkeypatch.setattr(cl, "_call_model", fake)
    out = await cl.compose_cover_letter(_master(), _opp())
    assert out["source"] == "model" and out["content"] == GOOD_LETTER
    assert len(calls) == 1
    assert "<untrusted_web_content>" in calls[0]  # job text is fenced as data


@pytest.mark.asyncio
async def test_compose_regenerates_once_with_the_problems_then_accepts(monkeypatch):
    drafts = ["Dear Hiring Team at 1Password,\n\nI am [Your Name].", GOOD_LETTER]
    prompts = []

    async def fake(system, user):
        prompts.append(user)
        return drafts.pop(0)

    monkeypatch.setattr(cl, "_call_model", fake)
    out = await cl.compose_cover_letter(_master(), _opp())
    assert out["source"] == "model"
    assert len(prompts) == 2
    assert "previous draft had these problems" in prompts[1]


@pytest.mark.asyncio
async def test_compose_falls_back_to_the_clean_template_after_two_bad_drafts(monkeypatch):
    calls = []

    async def fake(system, user):
        calls.append(1)
        return "Dear Hiring Team at 1Password,\n\nFor example, I built used by 200 students.."

    monkeypatch.setattr(cl, "_call_model", fake)
    out = await cl.compose_cover_letter(_master(), _opp())
    assert len(calls) == 2  # regenerate exactly once
    assert out["source"] == "template"
    assert out["problems"]
    assert cl.validate_cover_letter(out["content"], full_name="Priya Sharma", company="1Password") == []


@pytest.mark.asyncio
async def test_compose_uses_the_template_when_there_is_no_model(monkeypatch):
    async def fake(system, user):
        return ""

    monkeypatch.setattr(cl, "_call_model", fake)
    out = await cl.compose_cover_letter(_master(), _opp())
    assert out["source"] == "template"
    assert "Priya Sharma" in out["content"]


@pytest.mark.asyncio
async def test_model_call_is_skipped_in_the_test_environment():
    # ENVIRONMENT is "test" under pytest, so the provider is never contacted from the suite.
    assert await cl._call_model("system", "user") == ""
