"""Agent answer honesty: internal-text scrubbing and the deterministic schedule table (no database)."""

import importlib
import inspect
import time

import pytest

_SCRUB_MODULES = (
    "backend.agents.honesty",
    "backend.agents.scrub",
    "backend.agents.text",
    "backend.agent",
    "backend.agents.specialist",
    "backend.services.agent_text",
    "backend.services.agent_honesty",
    "backend.services.text_scrub",
    "backend.agents.schedule_deterministic",
)


def _find(name):
    for mod_name in _SCRUB_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    pytest.fail(f"{name} not found in any of {_SCRUB_MODULES}")


@pytest.fixture
def scrub():
    return _find("scrub_internal_agent_text")


BANNED = [
    "This satisfies the reviewer's request.",
    "Changes made per reviewer feedback.",
    "This is the previously approved schedule.",
    "Adjusted per critic feedback.",
]


@pytest.mark.parametrize("bad", BANNED)
def test_scrub_removes_internal_sentences(scrub, bad):
    out = scrub(f"Write unit tests is due Nov 30. {bad} Review PR is due Dec 2.")
    assert bad.rstrip(".") not in out
    assert "Write unit tests is due Nov 30." in out
    assert "Review PR is due Dec 2." in out


def test_scrub_keeps_normal_text(scrub):
    text = "Write unit tests is due Nov 30."
    assert scrub(text) == text


def test_scrub_is_idempotent(scrub):
    text = "Plan ready. Changes made per reviewer feedback. Write unit tests is due Nov 30."
    once = scrub(text)
    assert scrub(once) == once


@pytest.mark.parametrize("empty", ["", None, "   "])
def test_scrub_handles_empty(scrub, empty):
    out = scrub(empty)
    assert isinstance(out, str)
    assert out.strip() == ""


def test_scrub_large_whitespace_input_is_fast(scrub):
    text = "a" * 50000 + " " * 50000
    assert len(text) == 100000
    start = time.perf_counter()
    scrub(text)
    assert time.perf_counter() - start < 1.0


# --- deterministic schedule table -------------------------------------------------

_TABLE_CANDIDATES = (
    "build_schedule_table",
    "render_schedule_table",
    "format_schedule_table",
    "build_deterministic_schedule_table",
    "render_deadline_table",
    "build_due_table",
)


def _table_fn():
    for mod_name in _SCRUB_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for name in _TABLE_CANDIDATES:
            fn = getattr(mod, name, None)
            if callable(fn):
                return fn
    pytest.fail(f"schedule table helper not found (tried {_TABLE_CANDIDATES})")


REAL_TASKS = {
    1: {"id": 1, "title": "Write unit tests", "due_date": "2026-11-30", "priority": "high"},
    2: {"id": 2, "title": "Review PR", "due_date": "2026-12-02", "priority": "medium"},
}
BLOCKS = [
    {"task_id": 1, "title": "Write unit tests", "start": "2026-11-28T09:00:00+00:00", "end": "2026-11-28T10:00:00+00:00"},
    {"task_id": 2, "title": "Review PR", "start": "2026-11-29T09:00:00+00:00", "end": "2026-11-29T09:30:00+00:00"},
]


def _real_table_fn():
    import backend.agents.schedule_deterministic as sd
    return sd.build_deterministic_schedule_table, sd.patch_schedule_answer


def test_table_shows_real_due_dates_not_model_text():
    build, _ = _real_table_fn()
    out = build(BLOCKS, REAL_TASKS)
    assert "Mon Nov 30" in out
    assert "Wed Dec 2" in out
    assert "Nov 26" not in out


def test_table_puts_tasks_due_on_asked_day_first():
    from datetime import date
    build, _ = _real_table_fn()
    out = build(BLOCKS[::-1], REAL_TASKS, target_date=date(2026, 11, 30))
    assert "Write unit tests" in out  # due on the asked day, always listed
    if "Review PR" in out:
        assert out.index("Write unit tests") < out.index("Review PR")


def test_unsaved_plan_sentence_when_blocks_exist_and_nothing_committed():
    _, patch = _real_table_fn()
    out = patch("Here is your plan.", BLOCKS, REAL_TASKS, "plan my week", committed=False)
    assert "Nothing is saved yet" in out
    committed = patch("Here is your plan.", BLOCKS, REAL_TASKS, "plan my week", committed=True)
    assert "Nothing is saved yet" not in committed
