"""CI gate: every case in eval/intake_cases.py routes to its expected outcome."""

import pytest

from eval.intake_cases import CASES, decide


@pytest.mark.asyncio
@pytest.mark.parametrize("message, expected", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
async def test_intake_case(message, expected):
    assert await decide(message) == expected
