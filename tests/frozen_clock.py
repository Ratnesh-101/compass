"""Deterministic clock for Tavily verdict tests.

The verdict logic compares fixture dates against the real current date, so tests
that use hard-coded 2026 deadlines flip to STALE once those dates pass. This
fixture pins "now" for the two modules that read the clock, without changing
production code or any assertion.
"""
import datetime as _dt

import pytest

FROZEN_NOW = _dt.datetime(2026, 10, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


class _FrozenDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz else FROZEN_NOW.replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return FROZEN_NOW.date()


@pytest.fixture
def frozen_clock(monkeypatch):
    from backend.services import tavily_deadline, tavily_pipeline

    monkeypatch.setattr(tavily_pipeline, "datetime", _FrozenDatetime)
    monkeypatch.setattr(tavily_deadline, "date", _FrozenDate)
