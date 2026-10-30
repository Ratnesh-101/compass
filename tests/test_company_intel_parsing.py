"""
Tests for company intelligence JSON parsing, <think> block stripping, and grounding (Step 5).
"""

import logging
from backend.services.company_intel_jobs import (
    _parse_json_safely,
    _normalize_source_id,
    is_point_grounded,
)


def test_parse_json_safely_with_think_block():
    """Reasoning model output with <think> block containing braces is stripped cleanly."""
    captured_output = """
<think>
Let's see what the company priorities are:
{ "internal_scratchpad": "analyze Stripe payment APIs" }
We should format the output with summary and priorities.
</think>
```json
{
  "summary": "Stripe provides developer infrastructure for online and in-person payments globally.",
  "priorities": [
    {"point": "Expanding real-time payment rails.", "source": 1}
  ]
}
```
Hope this helps!
"""
    parsed = _parse_json_safely(captured_output)
    assert parsed is not None
    assert "Stripe provides developer infrastructure" in parsed.get("summary", "")
    assert len(parsed.get("priorities", [])) == 1
    assert parsed["priorities"][0]["source"] == 1


def test_parse_json_safely_with_preamble_and_fences():
    """Model output with leading conversational text and markdown code fences parses successfully."""
    captured_output = """
Here is the requested company intelligence brief for Stripe in JSON format:

```json
{
  "summary": "Global financial infrastructure platform.",
  "priorities": [{"point": "Accelerating revenue automation", "source": 1}],
  "challenges": [{"point": "Managing complex regulatory frameworks", "source": 2}],
  "talking_points": [{"point": "Experience building resilient webhook delivery systems", "source": 1}]
}
```

Let me know if you would like me to expand on any point.
"""
    parsed = _parse_json_safely(captured_output)
    assert parsed is not None
    assert parsed.get("summary") == "Global financial infrastructure platform."
    assert len(parsed.get("challenges", [])) == 1


def test_parse_json_safely_structural_logging(caplog):
    """When JSON is genuinely broken, only structural metadata is logged, never secrets or text."""
    bad_output = "<think>scratchpad</think>This is definitely not JSON {broken: bad}"
    with caplog.at_level(logging.WARNING):
        parsed = _parse_json_safely(bad_output)
        assert parsed is None

    # Check that structural markers were logged
    assert any("[STRUCTURE]" in record.message for record in caplog.records)
    # Check that raw scraped/input text is not logged
    assert not any("This is definitely not JSON" in record.message for record in caplog.records)


def test_normalize_source_id_formats():
    """Source IDs in various forms (int, string, bracketed, dict, list) are safely normalized."""
    valid_ids = {1, 2, 3}
    assert _normalize_source_id(1, valid_ids) == 1
    assert _normalize_source_id("1", valid_ids) == 1
    assert _normalize_source_id("[2]", valid_ids) == 2
    assert _normalize_source_id("Source 3", valid_ids) == 3
    assert _normalize_source_id({"id": 2}, valid_ids) == 2
    assert _normalize_source_id([3], valid_ids) == 3
    assert _normalize_source_id(0, valid_ids) == 1  # 0-based offset fallback to 1


def test_is_point_grounded_validation():
    """Grounding checks verify content tokens and metrics against sources."""
    sources = [
        {
            "id": 1,
            "title": "Stripe Infrastructure Engineering",
            "snippet": "Stripe processed over $1 trillion in total payment volume in 2024 across 50 countries.",
            "url": "https://stripe.com/newsroom/2024",
        }
    ]

    # Valid grounded point
    valid_point = "Processed over $1 trillion in total payment volume across global markets."
    assert is_point_grounded(valid_point, sources[0], sources) is True

    # Hallucinated metric ($500 billion or 99%)
    unsupported_metric = "Processed over $500 billion in total volume."
    assert is_point_grounded(unsupported_metric, sources[0], sources) is False

    # Completely unrelated tokens
    unrelated_point = "Quantum cryptographic satellite teleportation array."
    assert is_point_grounded(unrelated_point, sources[0], sources) is False


def test_balanced_brace_scanner_edge_cases():
    """Verify balanced brace scanner with string braces, escaped quotes, nested objects, and unterminated text."""
    # 1. Braces inside JSON strings
    s1 = 'Here is the data: {"summary": "Company builds {custom} solutions {and} widgets", "val": 1} Hope this helps!'
    p1 = _parse_json_safely(s1)
    assert p1 is not None
    assert p1["summary"] == "Company builds {custom} solutions {and} widgets"
    assert p1["val"] == 1

    # 2. Escaped quotes inside JSON strings
    s2 = 'Output: {"summary": "Company is \\"deeply innovative\\" in payments", "status": "ok"}'
    p2 = _parse_json_safely(s2)
    assert p2 is not None
    assert 'deeply innovative' in p2["summary"]

    # 3. Nested objects
    s3 = '{"summary": "Platform", "meta": {"deep": {"val": 42}, "tags": ["fintech"]}}'
    p3 = _parse_json_safely(s3)
    assert p3 is not None
    assert p3["meta"]["deep"]["val"] == 42

    # 4. Text after JSON
    s4 = '{"summary": "Single object"} Extra trailing model commentary.'
    p4 = _parse_json_safely(s4)
    assert p4 is not None
    assert p4["summary"] == "Single object"

    # 5. Two JSON objects (extracts the first valid object)
    s5 = '{"first": 1} {"second": 2}'
    p5 = _parse_json_safely(s5)
    assert p5 is not None
    assert p5.get("first") == 1

    # 6. Unterminated output (returns None gracefully without crashing)
    s6 = '{"summary": "Incomplete output that cuts off before closing'
    p6 = _parse_json_safely(s6)
    assert p6 is None
