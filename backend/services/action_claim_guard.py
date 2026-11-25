"""Action Claim Guard Service.

Detects unbacked first-person completion claims in model responses when no action or tool
actually executed during the turn, and replaces them with an honest, actionable response
requesting user confirmation.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Action verbs indicating completion or modification
CLAIM_VERBS = (
    r"added|created|updated|changed|edited|moved|rescheduled|scheduled|saved|"
    r"deleted|removed|marked|completed|set|submitted|sent|applied|booked|"
    r"exported|connected|renamed|cancelled|canceled|committed|locked"
)

# First-person phrasing prefixes
FIRST_PERSON_PREFIXES = (
    r"i(?:['’]ve|\s+have|\s+just|\s+went\s+ahead\s+and|['’]ll\s+have)"
)

# First-person completion claims: prefix followed within 3 words by an action verb
FIRST_PERSON_CLAIM_PATTERN = re.compile(
    r"\b(?:" + FIRST_PERSON_PREFIXES + r")(?:\s+\w+){0,3}\s+(?:" + CLAIM_VERBS + r")\b",
    re.IGNORECASE,
)

# Standalone openers and completion claims
OPENER_CLAIM_PATTERN = re.compile(
    r"(?:"
    r"(?:^|(?<=[.!?\n,]))\s*done\b(?:\s*[—–\-:])?|"
    r"\ball\s+set\b|"
    r"\bupdated\s+to\b|"
    r"\bupdated\s+(?:the\s+)?(?:task|deadline|due\s+date|reminder)\b|"
    r"\badded\s+\d+\s+tasks?\b|"
    r"\badded\s+(?:the\s+)?task\b|"
    r"\badded\s*:|"
    r"\btasks?\s+(?:created|added|updated|deleted|removed|completed|scheduled|saved)\b|"
    r"\b(?:areas?|category|categories|projects?|chats?)\s+(?:created|added|saved|renamed|deleted|removed)\b|"
    r"(?:^|(?<=[.!?\n]))\s*(?:[a-zA-Z0-9_\'-]+\s+){1,4}(?:created|added|saved|renamed|deleted|removed)\b|"
    r"\b(?:marked|moved|rescheduled|scheduled|deleted|removed|renamed|saved|submitted|applied|booked|exported|cancelled|canceled)\b[^\n.!?]{0,80}?\b(?:as\s+(?:done|complete)|to|for|on|in|from)\b|"
    r"\b(?:it['’]?s|it\s+is|they['’]?re|they\s+are)\s+now\s+(?:on|in)\s+your\s+(?:list|schedule|calendar|timeline|watchlist)\b|"
    r"\bnow\s+on\s+your\s+list\b|"
    r"\bi['’]ve\s+set\b|"
    r"\byour\s+task\s+has\s+been\s+(?:\w+\s+){0,2}(?:added|updated|deleted|scheduled|rescheduled|submitted|saved|completed)\b|"
    r"\bhas\s+been\s+(?:\w+\s+){0,2}(?:added|updated|deleted|scheduled|rescheduled|submitted|saved|completed)\b"
    r")",
    re.IGNORECASE,
)

# Action verbs and completion tokens used to identify the claim verb position
CLAIM_VERB_PATTERN = re.compile(
    r"\b(?:" + CLAIM_VERBS + r"|done)\b",
    re.IGNORECASE,
)

# Negation words and phrases that exempt a sentence from claim detection
NEGATION_PATTERN = re.compile(
    r"\b(?:"
    r"not|"
    r"never|"
    r"nothing|"
    r"no[-–\s]+one|"
    r"nobody|"
    r"none|"
    r"without|"
    r"cannot|"
    r"can['’]t|"
    r"couldn['’]t|"
    r"won['’]t|"
    r"unable|"
    r"haven['’]t|"
    r"hasn['’]t|"
    r"didn['’]t|"
    r"no\s+tasks?|"
    r"no\s+applications?|"
    r"no\s+changes?"
    r")\b|n['’]t\b",
    re.IGNORECASE,
)

# Offers and exploratory phrasing that must not trigger false positives
OFFER_PATTERN = re.compile(
    r"\b(?:"
    r"would\s+you\s+like\s+me\s+to|"
    r"do\s+you\s+want\s+me\s+to|"
    r"i\s+can\s+add|"
    r"i\s+can\s+update|"
    r"should\s+i|"
    r"shall\s+i|"
    r"want\s+me\s+to"
    r")\b",
    re.IGNORECASE,
)

# Classification pattern for task add / update / schedule claims
TASK_CLAIM_PATTERN = re.compile(
    r"\b(?:"
    r"updated\s+(?:the\s+)?(?:task|deadline|due\s+date|reminder)|"
    r"updated\s+to|"
    r"added\s+\d+\s+tasks?|"
    r"added\s*:|"
    r"tasks?\s+(?:created|added|updated|deleted|removed|completed|scheduled|saved)|"
    r"task\s+updated|"
    r"task\s+added|"
    r"added\s+the\s+task|"
    r"(?:it['’]?s|it\s+is|they['’]?re|they\s+are)\s+now\s+(?:on|in)\s+your\s+(?:list|schedule|calendar|timeline|watchlist)|"
    r"now\s+on\s+your\s+list|"
    r"your\s+task\s+has\s+been\s+(?:added|updated|rescheduled|scheduled|completed)|"
    r"(?:i(?:['’]ve|\s+have|\s+just|\s+went\s+ahead\s+and|['’]ll\s+have))(?:\s+\w+){0,3}\s+"
    r"(?:added|created|updated|changed|edited|moved|rescheduled|scheduled|set)"
    r")\b",
    re.IGNORECASE,
)

# Classification pattern for application submit / apply claims
SUBMIT_APPLY_CLAIM_PATTERN = re.compile(
    r"\b(?:"
    r"(?:i(?:['’]ve|\s+have|\s+just|\s+went\s+ahead\s+and|['’]ll\s+have))(?:\s+\w+){0,3}\s+"
    r"(?:submitted|applied)|"
    r"application\s+has\s+been\s+submitted|"
    r"your\s+task\s+has\s+been\s+submitted|"
    r"has\s+been\s+submitted|"
    r"(?:submitted|applied)\s+(?:your\s+|the\s+)?(?:application|internship|job)"
    r")\b",
    re.IGNORECASE,
)

HONEST_PREFIX = "I haven't changed anything yet, so I won't say I did. "
TASK_NEXT_STEP = (
    "Tell me the task and the exact date and time, and I'll show a confirmation card before saving it."
)
SUBMIT_NEXT_STEP = (
    "I can't submit applications for you without your confirmation, and nothing has been submitted. "
    "Open the Career tab to review and submit it yourself."
)
GENERAL_NEXT_STEP = (
    "Tell me exactly what you want changed and I'll show a confirmation card first."
)


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences while respecting common sentence boundaries."""
    raw_parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in raw_parts if p.strip()]


def _strip_quotes(sentence: str) -> str:
    """Remove quoted substrings to prevent user quotes from confusing detection."""
    cleaned = re.sub(r'["“][^"”]*["”]', '""', sentence)
    cleaned = re.sub(r"(?<=[\s:,(])'[^']+'(?=[\s:,.!?]|$)", "''", cleaned)
    return cleaned


def _has_unnegated_claim(text: str) -> bool:
    """Check if text contains any action claim that is not negated."""
    matches = list(FIRST_PERSON_CLAIM_PATTERN.finditer(text)) + list(
        OPENER_CLAIM_PATTERN.finditer(text)
    )
    if not matches:
        return False

    neg_matches = list(NEGATION_PATTERN.finditer(text))

    for m in matches:
        verb_matches = list(CLAIM_VERB_PATTERN.finditer(m.group(0)))
        v = verb_matches[-1] if verb_matches else None
        verb_start = m.start() + (v.start() if v else 0)
        verb_end = m.start() + (v.end() if v else len(m.group(0)))

        # A sentence is exempt when a negation word or phrase appears anywhere
        # before or right at the claim verb.
        is_negated = any(
            neg.start() <= verb_start or (neg.start() <= verb_end and neg.end() >= verb_start)
            for neg in neg_matches
        )
        if not is_negated:
            return True

    return False


def _is_claim(sentence: str) -> bool:
    """Check if a single sentence constitutes an unbacked action completion claim."""
    trimmed = sentence.strip()
    if not trimmed:
        return False

    # Questions are offers or inquiries, not completion claims
    if trimmed.endswith("?"):
        return False

    # Offers must not trigger
    if OFFER_PATTERN.search(trimmed):
        return False

    # Check the sentence with quoted user words stripped
    unquoted = _strip_quotes(trimmed)
    if OFFER_PATTERN.search(unquoted) or unquoted.endswith("?"):
        return False

    if _has_unnegated_claim(unquoted):
        return True

    # Check raw sentence if claim itself was enclosed in quotes (unless attributing user speech)
    if _has_unnegated_claim(trimmed):
        if not re.search(
            r"\b(?:you\s+(?:said|asked|wrote|mentioned)|user\s*[:>])",
            trimmed,
            re.IGNORECASE,
        ):
            return True

    return False


def _select_honest_text(claim_sentences: List[str]) -> str:
    """Select the appropriate honest response and next step based on claim context."""
    combined = " ".join(claim_sentences)

    # Submit / apply claims have specific guidance
    if SUBMIT_APPLY_CLAIM_PATTERN.search(combined):
        return HONEST_PREFIX + SUBMIT_NEXT_STEP

    # Task add / update / reschedule claims
    if TASK_CLAIM_PATTERN.search(combined):
        return HONEST_PREFIX + TASK_NEXT_STEP

    # Generic modifications
    return HONEST_PREFIX + GENERAL_NEXT_STEP


def guard_unbacked_action_claims(
    reply: str, action_executed: bool
) -> Tuple[str, bool]:
    """Guard against plain-text replies claiming actions that never executed.

    Args:
        reply: The model's proposed text reply.
        action_executed: True if a tool, skill, or verified action actually executed.

    Returns:
        tuple of (guarded_text, was_replaced).
    """
    if action_executed or not reply or not reply.strip():
        return reply, False

    sentences = _split_into_sentences(reply)
    if not sentences:
        return reply, False

    first_claim_idx = -1
    for idx, sentence in enumerate(sentences):
        if _is_claim(sentence):
            first_claim_idx = idx
            break

    if first_claim_idx == -1:
        return reply, False

    # Keep any harmless non-claim sentences of the original reply that precede the claim (max 2)
    harmless_preceding = [
        s for s in sentences[:first_claim_idx] if not _is_claim(s)
    ][:2]

    claim_sentences = sentences[first_claim_idx:]
    honest_text = _select_honest_text(claim_sentences)

    if harmless_preceding:
        formatted_preceding = []
        for s in harmless_preceding:
            s_clean = s.strip()
            if s_clean and not s_clean.endswith((".", "!", "?")):
                s_clean += "."
            formatted_preceding.append(s_clean)
        prefix = " ".join(formatted_preceding)
        result_text = f"{prefix} {honest_text}"
    else:
        result_text = honest_text

    return result_text, True


# State claims that cannot be backed by a tool in a plain reply
STATE_CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:the\s+[^\n.!?]{0,40}?\s+)?(?:you|you['’]ve|you\s+have)\s+saved\s+(?:it|this|that|the\b[^\n.!?]{0,40}?)?\s*earlier\b",
        re.IGNORECASE,
    ),
    re.compile(r"\byour\s+task\s+list\s+is\s+(?:currently\s+)?empty\b", re.IGNORECASE),
    re.compile(r"\byou\s+have\s+no\s+(?:open\s+|active\s+)?tasks\b", re.IGNORECASE),
)

EMPTY_TASK_CLAIM_PATTERNS = (
    re.compile(r"\byour\s+task\s+list\s+is\s+(?:currently\s+)?empty\b", re.IGNORECASE),
    re.compile(r"\byou\s+have\s+no\s+(?:open\s+|active\s+)?tasks\b", re.IGNORECASE),
)


def guard_state_claims(
    reply: str, known_task_count: Optional[int]
) -> Tuple[str, bool]:
    """Guard against plain-text replies claiming no tasks when tasks exist.

    Args:
        reply: Proposed assistant reply text.
        known_task_count: Count of known active tasks, or None.

    Returns:
        tuple of (guarded_text, was_replaced).
    """
    if not reply or not reply.strip():
        return reply, False

    if known_task_count is None or known_task_count <= 0:
        return reply, False

    has_empty_claim = any(p.search(reply) for p in EMPTY_TASK_CLAIM_PATTERNS)
    if not has_empty_claim:
        return reply, False

    plural = "s" if known_task_count != 1 else ""
    replacement = f"You have {known_task_count} open task{plural}."
    return replacement, True

