"""Top-3 picker: technical, relevant listings only; HR and payroll roles never fill the slots."""
from types import SimpleNamespace

from backend.services.career_top_picks import only_n_message, relevance_score, select_relevant

SKILLS = ["Python", "React", "Languages: JavaScript, SQL"]


def _o(title, description=""):
    return SimpleNamespace(role_title=title, description=description)


CANDIDATES = [
    _o("Talent Acquisition Intern", "Source candidates and coordinate interviews."),
    _o("Backend Intern (Python)"),
    _o("Frontend Intern (React)"),
    _o("Payroll Trainee", "Process monthly payroll."),
    _o("ML Intern"),
]


def test_top_three_are_the_technical_listings():
    picked = select_relevant(CANDIDATES, SKILLS)[:3]
    assert [o.role_title for o in picked] == ["Backend Intern (Python)", "Frontend Intern (React)", "ML Intern"]


def test_hr_and_payroll_roles_are_excluded():
    titles = [o.role_title for o in select_relevant(CANDIDATES, SKILLS)]
    assert "Talent Acquisition Intern" not in titles
    assert "Payroll Trainee" not in titles


def test_ranked_order_is_kept_for_fresh_listings():
    reordered = [CANDIDATES[2], CANDIDATES[4], CANDIDATES[1]]
    assert [o.role_title for o in select_relevant(reordered, SKILLS)] == [o.role_title for o in reordered]


def test_non_technical_penalty_applies_even_when_description_mentions_a_skill():
    hr = _o("HR Intern", "Maintain Python spreadsheets for the recruiting team.")
    assert relevance_score(hr, SKILLS) <= 0


def test_skill_in_description_makes_a_generic_title_relevant():
    assert relevance_score(_o("Intern", "You will build services in Python."), SKILLS) > 0


def test_only_n_message_when_fewer_than_three():
    assert only_n_message(2, 3) == "Only 2 listings matched your profile"
    assert only_n_message(3, 3) == ""
    assert only_n_message(0, 3) == "Only 0 listings matched your profile"
