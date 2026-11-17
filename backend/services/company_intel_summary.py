"""
Compass - Plain summary for company intel when the model could not write one (N-019 / T-025).

When the model call fails but cleaned source snippets exist, the brief used to say
"Sources found, summary unavailable" next to raw scraped text. This module builds a short summary
(at most three sentences) by quoting whole sentences from the sources, and rejects the snippets
that are scraped data dumps ("ID: Jwu4pnzXlRGp Website: www.example.com Headquarters: ...").
If nothing clean is left the caller shows one plain message instead.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

UNAVAILABLE_MESSAGE = "Couldn't summarise this company right now."
FALLBACK_LABEL = "Quoted from public sources"
MAX_SUMMARY_SENTENCES = 3
MAX_SENTENCE_WORDS = 28
MIN_SENTENCE_WORDS = 6

_KEY_VALUE_RE = re.compile(r"\b[A-Z][A-Za-z]{1,20}(?: [A-Za-z]{1,15})?:\s")
_ID_TOKEN_RE = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{10,}\b")
_URL_OR_EMAIL_RE = re.compile(r"https?://|www\.|\b[\w.+-]+@[\w-]+\.\w+", re.IGNORECASE)


def is_scrape_dump(text: str) -> bool:
    """True for field-label dumps, ID strings, links and other text that is not a readable sentence."""
    t = (text or "").strip()
    if not t:
        return True
    if len(_KEY_VALUE_RE.findall(t)) >= 2:
        return True
    if _ID_TOKEN_RE.search(t):
        return True
    if _URL_OR_EMAIL_RE.search(t):
        return True
    return False


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _readable(sentence: str) -> bool:
    words = sentence.split()
    if not (MIN_SENTENCE_WORDS <= len(words) <= MAX_SENTENCE_WORDS):
        return False
    if is_scrape_dump(sentence):
        return False
    if not (sentence[0].isupper() or sentence[0].isdigit()):
        return False
    return sentence[-1] in ".!?"


def extractive_summary(sources: List[Dict[str, Any]], max_sentences: int = MAX_SUMMARY_SENTENCES) -> str:
    """Up to `max_sentences` whole, readable sentences quoted from different sources; '' when none qualify."""
    picked: List[str] = []
    seen: set[str] = set()
    for src in sources or []:
        for sentence in _sentences(str(src.get("snippet") or "")):
            if not _readable(sentence):
                continue
            key = re.sub(r"\W+", " ", sentence.lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            picked.append(sentence)
            break  # one sentence per source keeps the summary varied
        if len(picked) >= max_sentences:
            break
    return " ".join(picked)
