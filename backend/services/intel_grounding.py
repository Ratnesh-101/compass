"""
Compass — pure text helpers for Company Intel: untrusted-text sanitising, company-name token
matching, strict source grounding and evidence-derived confidence. No I/O.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set


STOPWORDS: Set[str] = {
    "the", "and", "that", "this", "with", "from", "have", "been", "will",
    "they", "their", "them", "what", "which", "about", "role", "team",
    "company", "focus", "work", "also", "into", "over", "more", "most",
    "such", "some", "other", "than", "then", "when", "where", "while",
    "for", "are", "can", "could", "should", "would", "its", "has", "had",
    "you", "your", "our", "were", "who", "whom", "whose"
}


GENERIC_COMPANY_TOKENS: Set[str] = {
    "inc", "llc", "ltd", "labs", "lab", "tech", "technologies", "group", "corp",
    "co", "company", "the", "systems", "software",
}

_INJECTION_PREFIXES = (
    "ignore", "disregard", "system:", "assistant:", "you are", "forget",
    "new instructions", "do not follow",
)


def _word_tokens(text: str) -> List[str]:
    """Lowercase alphanumeric tokens (bounded pattern, no nested quantifiers)."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _looks_like_instruction(text: str) -> bool:
    return text.strip().lstrip("\"'([-*>").lower().startswith(_INJECTION_PREFIXES)


def sanitize_untrusted_text(text: str) -> str:
    """Neutralise scraped text before it reaches the model: no source delimiters, fake headers or instructions."""
    cleaned_lines = []
    for line in str(text or "").splitlines():
        if not _looks_like_instruction(line):
            cleaned_lines.append(line)
    out = " ".join(cleaned_lines)
    low = out.lower()
    for marker in ("</source", "<source"):
        while marker in low:
            idx = low.find(marker)
            out = out[:idx] + out[idx + len(marker):]
            low = out.lower()
    out = re.sub(r"\[\s{0,3}source\s{1,3}\d{1,3}\s{0,3}\]", " ", out, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!?])\s+", out)
    return " ".join(sn for sn in sentences if not _looks_like_instruction(sn))


def _distinctive_company_tokens(company_name: str) -> List[str]:
    toks = [t for t in _word_tokens(company_name) if len(t) >= 2]
    distinctive = [t for t in toks if t not in GENERIC_COMPANY_TOKENS]
    return distinctive or toks


GROUNDING_THRESHOLD = 0.6
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _token_supported(tok: str, source_tokens: Set[str]) -> bool:
    if tok in source_tokens or tok + "s" in source_tokens:
        return True
    return tok.endswith("s") and tok[:-1] in source_tokens


def is_point_grounded(
    point_text: str,
    cited_source: Dict[str, Any],
    all_sources: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Verifies that a summarized point is supported by the SPECIFIC source it cites.

    - Every number in the point must appear exactly in the cited source (1-6 included).
    - At least 60% of the point's content words (stopwords removed) must appear as whole
      tokens in the cited source. `all_sources` is accepted for compatibility but unused.
    """
    if not point_text:
        return False

    source_text = f"{cited_source.get('snippet', '')} {cited_source.get('title', '')}".lower()
    point_numbers = set(_NUMBER_PATTERN.findall(point_text))
    if point_numbers and not point_numbers.issubset(set(_NUMBER_PATTERN.findall(source_text))):
        return False

    tokens = [t for t in _word_tokens(point_text) if len(t) >= 3 and not t.isdigit() and t not in STOPWORDS]
    if not tokens:
        return False

    source_tokens = set(_word_tokens(source_text))
    supported = sum(1 for tok in tokens if _token_supported(tok, source_tokens))
    return supported / len(tokens) >= GROUNDING_THRESHOLD


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _derive_confidence(brief: Dict[str, Any], model_claim: str) -> str:
    """Confidence from surviving evidence, never higher than the model claimed."""
    points = [p for sec in ("priorities", "role_context", "challenges", "talking_points") for p in brief[sec]]
    distinct_sources = {p["source"] for p in points}
    if len(points) >= 4 and len(distinct_sources) >= 3:
        derived = "high"
    elif len(points) >= 2:
        derived = "medium"
    else:
        derived = "low"
    if model_claim in _CONFIDENCE_RANK and _CONFIDENCE_RANK[model_claim] < _CONFIDENCE_RANK[derived]:
        return model_claim
    return derived
