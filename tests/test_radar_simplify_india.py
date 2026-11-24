"""India eligibility and country derivation for SimplifyJobs rows. No network, no database."""
from __future__ import annotations

import pytest

from backend.services.radar_simplify import normalize_simplify_listing

PAST_TS = 1_700_000_000


def _norm(locations):
    return normalize_simplify_listing(
        {
            "active": True,
            "is_visible": True,
            "category": "Software",
            "url": "https://example.com/jobs/1",
            "company_name": "Acme",
            "title": "Software Engineer Intern",
            "locations": locations,
            "date_posted": PAST_TS,
            "terms": ["Summer 2027"],
        }
    )


def test_indianapolis_is_not_india():
    out = _norm(["Indianapolis, IN"])
    assert out["is_india_eligible"] is False
    assert out["country"] == "USA"


def test_indiana_is_not_india():
    assert _norm(["Indiana"])["is_india_eligible"] is False


def test_us_states_including_indiana_are_not_india():
    out = _norm(["St. Louis, MO", "Missouri", "Indiana"])
    assert out["is_india_eligible"] is False
    assert out["country"] == "USA"


def test_pune_india():
    out = _norm(["Pune, Maharashtra, India"])
    assert out["is_india_eligible"] is True
    assert out["country"] == "India"


def test_bengaluru_alone_is_india():
    assert _norm(["Bengaluru"])["is_india_eligible"] is True


def test_remote_in_india():
    assert _norm(["Remote in India"])["is_india_eligible"] is True


def test_remote_in_usa():
    out = _norm(["Remote in USA"])
    assert out["is_india_eligible"] is False
    assert out["country"] == "USA"


def test_cardiff_uk():
    out = _norm(["Cardiff, UK"])
    assert out["is_india_eligible"] is False
    assert out["country"] == "UK"


def test_london_united_kingdom():
    assert _norm(["London, United Kingdom"])["country"] == "UK"


def test_toronto_canada():
    assert _norm(["Toronto, Canada"])["country"] == "Canada"


def test_plain_remote_is_global():
    out = _norm(["Remote"])
    assert out["is_india_eligible"] is False
    assert out["country"] == "Global"


def test_multi_location_one_india_place_is_enough():
    assert _norm(["New York, NY", "Hyderabad, India"])["is_india_eligible"] is True


@pytest.mark.parametrize("loc", ["Indianapolis, IN", "Indiana"])
def test_indiana_variants_never_flag_india(loc):
    assert _norm([loc])["is_india_eligible"] is False
