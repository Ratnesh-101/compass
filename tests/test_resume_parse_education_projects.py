from backend.services.career_resume import parse_uploaded_resume_text

RAW_TEXT = """Jordan Testcandidate
jordan.testcandidate@example.invalid | +91 90000 00000 | Pune, India
github.com/jordan-testcandidate-fictional
Education
B.Tech in Computer Science, Fictional Institute of Technology, 2022 - 2026, CGPA 8.4/10
Skills
Python, SQL, PostgreSQL, React, FastAPI, Docker, Git
Projects
Campus Event Tracker - Built a FastAPI and React app that lists campus events with reminders. Used PostgreSQL for storage and Docker for deployment.
Study Planner Bot - Wrote a Python script that turns a syllabus into a weekly study schedule.
Experience
Software Intern, Example Labs (fictional), May 2025 - Jul 2025. Added unit tests and fixed bugs in an internal dashboard."""


def test_resume_parse_education_and_projects():
    parsed = parse_uploaded_resume_text(RAW_TEXT)

    # Education assertions
    assert len(parsed.education) == 1
    edu = parsed.education[0]
    assert edu.institution == "Fictional Institute of Technology"
    assert "B.Tech" in edu.degree
    assert edu.field_of_study == "Computer Science"
    assert edu.start_year == 2022
    assert edu.end_year == 2026
    assert edu.cgpa_or_grade == "8.4/10"

    # Projects assertions
    assert len(parsed.projects) == 2
    p1 = parsed.projects[0]
    assert p1.title == "Campus Event Tracker"
    assert p1.description == "Built a FastAPI and React app that lists campus events with reminders. Used PostgreSQL for storage and Docker for deployment."
    for tech in ["FastAPI", "React", "PostgreSQL", "Docker"]:
        assert tech in p1.technologies

    p2 = parsed.projects[1]
    assert p2.title == "Study Planner Bot"
    assert p2.description == "Wrote a Python script that turns a syllabus into a weekly study schedule."
    assert "Python" in p2.technologies


def test_resume_parse_project_without_description():
    text = """Jordan Testcandidate
Projects
Standalone Project Title
"""
    parsed = parse_uploaded_resume_text(text)
    assert len(parsed.projects) == 1
    p = parsed.projects[0]
    assert p.title == "Standalone Project Title"
    assert p.description != "Project implementation"
    assert p.description == ""


def _timed_parse(text):
    import time

    start = time.perf_counter()
    parsed = parse_uploaded_resume_text(text)
    return parsed, time.perf_counter() - start


def test_education_long_whitespace_run_is_linear():
    text = "Education\nB.Tech " + " " * 300000 + "Fictional Institute of Technology 2022 - 2026"
    parsed, elapsed = _timed_parse(text)
    print(f"ELAPSED whitespace {elapsed:.3f}s")
    assert elapsed < 2
    assert len(parsed.education) == 1
    assert "Fictional Institute of Technology" in parsed.education[0].institution


def test_education_many_pipes_is_linear():
    text = "Education\nB.Tech Fictional Institute of Technology " + "| " * 300000 + "2022 - 2026"
    parsed, elapsed = _timed_parse(text)
    print(f"ELAPSED pipes {elapsed:.3f}s")
    assert elapsed < 2
    assert len(parsed.education) == 1
    assert "Fictional Institute of Technology" in parsed.education[0].institution
