import time

from backend.services.career_resume import parse_uploaded_resume_text

INLINE_LINE = (
    "Software Intern, Example Labs (fictional), May 2025 - Jul 2025. "
    "Added unit tests and fixed bugs in an internal dashboard."
)


def _entries(content):
    return list(content.experience) + list(content.internships)


def test_inline_entry_with_trailing_sentence_splits_cleanly():
    content = parse_uploaded_resume_text("Experience\n" + INLINE_LINE)
    entries = _entries(content)
    assert len(entries) == 1
    item = entries[0]
    assert item.role_title == "Software Intern"
    assert item.company == "Example Labs (fictional)"
    assert item.start_date == "May 2025"
    assert item.end_date == "Jul 2025"
    assert item.is_current is False
    assert item.highlights == ["Added unit tests and fixed bugs in an internal dashboard."]


def test_company_pipe_role_with_bullets_unchanged():
    text = (
        "Experience\n"
        "Acme Cloud | Senior Software Engineer   Jan 2024 - Present\n"
        "- Architected multi-region event streaming pipeline.\n"
        "- Reduced end-to-end processing latency by 42%.\n"
    )
    entries = _entries(parse_uploaded_resume_text(text))
    assert len(entries) == 1
    item = entries[0]
    assert item.company == "Acme Cloud"
    assert item.start_date == "Jan 2024"
    assert item.end_date.lower() == "present"
    assert item.is_current is True
    assert len(item.highlights) == 2
    assert item.highlights[0].startswith("Architected multi-region")


def test_inline_entry_without_trailing_text():
    text = "Experience\nSoftware Engineer, Example Labs, May 2025 - Jul 2025"
    entries = _entries(parse_uploaded_resume_text(text))
    assert len(entries) == 1
    item = entries[0]
    assert item.role_title == "Software Engineer"
    assert item.company == "Example Labs"
    assert item.start_date == "May 2025"
    assert item.end_date == "Jul 2025"
    assert item.highlights == []


def test_adversarial_input_is_linear_time():
    text = (
        "Experience\nSoftware Intern, Example Labs "
        + " " * 300000
        + "May 2025 - Jul 2025. "
        + "x " * 100000
    )
    start = time.perf_counter()
    parse_uploaded_resume_text(text)
    elapsed = time.perf_counter() - start
    print(f"TIMING_ELAPSED={elapsed:.3f}s")
    assert elapsed < 2.0
