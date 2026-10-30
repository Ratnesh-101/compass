"""Guards that keep questions and capability asks from becoming tasks.

A task is only created from a concrete command with a meaningful title. A message that is
question-framed ("can you add deadlines for me?") is a request for information, not a task, unless
it still carries a concrete task ("can you add a task to buy milk tomorrow?").
"""

from __future__ import annotations

import difflib
import re
from typing import Optional

STATEMENT = "statement"
COMMAND = "command"
QUESTION = "question"

MAX_TITLE_LEN = 200

CAPABILITY_REPLY = (
    "Yes, I can add tasks and deadlines. I haven't added anything yet because I need the details. "
    "Tell me the task name and when it's due, for example: \"add task Submit report tomorrow 5pm\". "
    "You can also paste several tasks (a table or a list) and I'll show you a preview to confirm "
    "before anything is added."
)

TITLE_CLARIFICATION = (
    "I haven't added anything, because I couldn't find a clear task name. "
    "What should the task be called, and when is it due? "
    "For example: \"add task Submit report tomorrow 5pm\"."
)

_PRONOUN_LEAD = re.compile(
    r"^(?:can|could|would|will|do|does|did|are|is|am|may|might|should)\s+"
    r"(?:you|u|i|we|compass|it|this|that|there)\b"
)
# A title that is itself addressed to the assistant ("Can you deadlines for me"), not "Do it by Friday".
_TITLE_QUESTION_LEAD = re.compile(r"^(?:(?:can|could|would|will)\s+(?:you|u)|(?:do|does|are|is)\s+(?:you|compass))\b")
_WH_LEAD = re.compile(r"^(?:what|what's|whats|how|why|when|where|who|which)\b")
_POLITE_PREFIX = re.compile(
    r"^(?:(?:hey|hi|ok|okay)[,!]?\s+)?(?:"
    r"(?:would\s+you\s+mind\s+(?:adding|creating|setting|scheduling)\s+)"
    r"|(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+)?)"
    r"|please\s+"
    r")",
    re.IGNORECASE,
)
_CREATION_VERB = re.compile(
    r"\b(?:add(?:ing)?|creat(?:e|ing)|mak(?:e|ing)|sett?(?:ing)?|schedul(?:e|ing)|put(?:ting)?|track(?:ing)?|remind(?:ing)?)\b",
    re.IGNORECASE,
)
_CREATION_NOUN = re.compile(
    r"\b(?:tasks?|todos?|to-dos?|deadlines?|reminders?)\b",
    re.IGNORECASE,
)


class _LinearCreationPhraseMatcher:
    """Linear-time replacement for quadratic _CREATION_PHRASE regex."""

    pattern = (
        r"\b(?:add(?:ing)?|creat(?:e|ing)|mak(?:e|ing)|sett?(?:ing)?|schedul(?:e|ing)|put(?:ting)?|track(?:ing)?|remind(?:ing)?)\b"
        r".*\b(?:tasks?|todos?|to-dos?|deadlines?|reminders?)\b"
    )

    def search(self, text: str) -> Optional[re.Match]:
        if not text:
            return None
        truncated = text[:2000]
        v_match = _CREATION_VERB.search(truncated)
        if not v_match:
            return None
        return _CREATION_NOUN.search(truncated, v_match.end())


_CREATION_PHRASE = _LinearCreationPhraseMatcher()

CANONICAL_VERBS = ("add", "create", "schedule", "remind", "set")
CANONICAL_NOUNS = ("task", "tasks", "deadline", "deadlines", "reminder", "reminders", "todo", "todos")

KNOWN_TYPOS = {
    "taks": "task",
    "tsak": "task",
    "tak": "task",
    "ad": "add",
    "aad": "add",
    "craete": "create",
    "creat": "create",
    "crate": "create",
    "shedule": "schedule",
    "schedual": "schedule",
    "remnd": "remind",
    "remid": "remind",
    "mee": "me",
    "tomorow": "tomorrow",
}
_NON_NOUN_WORDS = frozenset(CANONICAL_VERBS) | {
    "me", "my", "to", "a", "an", "the", "please", "u", "you", "i", "we", "for", "in", "on", "at", "by", "of", "do", "ki",
}


def _fuzzy_first_and_noun(words: list[str]) -> list[str]:
    """Apply difflib.get_close_matches only to the single first word and the noun word."""
    if not words:
        return words
    result = list(words)
    first_clean = result[0].lower().rstrip(",:;?!'\"")
    if first_clean and first_clean not in CANONICAL_VERBS and len(first_clean) >= 3:
        match = difflib.get_close_matches(first_clean, CANONICAL_VERBS, n=1, cutoff=0.8)
        if match:
            punct = result[0][len(first_clean):]
            result[0] = match[0] + punct

    for idx in range(1, min(4, len(result))):
        w_clean = result[idx].lower().rstrip(",:;?!'\"")
        if w_clean and w_clean not in CANONICAL_NOUNS and w_clean not in _NON_NOUN_WORDS and len(w_clean) >= 3:
            match = difflib.get_close_matches(w_clean, CANONICAL_NOUNS, n=1, cutoff=0.8)
            if match:
                punct = result[idx][len(w_clean):]
                result[idx] = match[0] + punct
                break
    return result


def normalize_task_intent_text(text: str) -> str:
    """Map known typos, Hinglish verb phrases, and polite prefixes to canonical forms."""
    if not text:
        return ""
    s = text[:2000].strip()

    # Polite prefix: "would you mind creating/adding/setting/scheduling"
    m_mind = re.match(
        r"^(?:(?:hey|hi|ok|okay)[,!]?\s+)?would\s+you\s+mind\s+(adding|creating|setting|scheduling)\s+(.*)$",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if m_mind:
        verb = m_mind.group(1).lower()
        verb_map = {"adding": "add", "creating": "create", "setting": "set", "scheduling": "schedule"}
        s = f"{verb_map.get(verb, 'add')} {m_mind.group(2)}"

    # Hinglish patterns
    s = re.sub(r"^\s*mujhe\s+remind\s+(?:kar\s+dena|kar\s+do)\s+", "remind me ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bremind\s+(?:kar\s+dena|kar\s+do)\s+to\b", "remind me to", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*ek\s+task\s+(?:add|create)\s+kar\s+do\b", "add task", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:task\s+)?(?:add|create)\s+kar\s+do\b", "add task", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:task\s+)?bana\s+do\b", "create task", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*yeh\s+task\s+list\s+me\s+daal\s+do\s*(?:please\s*)?[:\-\u2013]?\s*", "add task: ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:task\s+)?list\s+me\s+daal\s+do\b", "add task", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdaal\s+do\b", "add", s, flags=re.IGNORECASE)
    s = re.sub(r"\bremind\s+me\s+ki\b", "remind me to", s, flags=re.IGNORECASE)
    s = re.sub(r"\bkal\b", "tomorrow", s, flags=re.IGNORECASE)

    # Dictionary replacement and difflib
    words = s.split()
    for i, w in enumerate(words):
        w_lower = w.lower().rstrip(",:;?!'\"")
        if w_lower in KNOWN_TYPOS:
            canon = KNOWN_TYPOS[w_lower]
            punct = w[len(w_lower):]
            words[i] = (canon[0].upper() + canon[1:] if w[0].isupper() else canon) + punct

    words = _fuzzy_first_and_noun(words)
    return " ".join(words)

# Words that, on their own, are not a task name.
_FILLER_WORDS = frozenset({
    "task", "tasks", "todo", "todos", "deadline", "deadlines", "reminder", "reminders", "me", "you",
    "for", "a", "an", "the", "please", "add", "create", "new", "set", "my", "to", "it", "this",
    "that", "some", "any", "of", "on", "in", "at", "by", "can", "could", "would", "will", "i",
    "kar", "karna", "sakte", "sakta", "sakti", "ho", "hain", "tum", "aap", "kya", "kaise", "kyun",
})

INTERROGATIVE_LEADS = frozenset({
    "did", "do", "does", "should", "would", "could", "can",
    "is", "are", "am", "was", "were",
    "why", "how", "what", "what's", "whats", "when", "where", "who", "which",
    "kya", "kaise", "kyun",
})


def _strip_quoted_text(text: str) -> str:
    """Return text with substrings inside quotation marks replaced by whitespace,
    unless the entire text is wrapped in matching quotes.
    """
    s = text.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"') and s.count('"') == 2) or \
       (s.startswith("'") and s.endswith("'") and s.count("'") == 2):
        return s[1:-1].strip()

    chars = []
    in_double = False
    in_single = False
    n = len(text)
    for i, ch in enumerate(text):
        if ch in ('"', '“', '”'):
            in_double = not in_double
            chars.append(' ')
        elif ch in ("'", '‘', '’'):
            is_word_apostrophe = i > 0 and text[i - 1].isalnum()
            is_contraction = is_word_apostrophe and (i + 1 < n and text[i + 1].isalnum())
            if not in_single:
                if is_word_apostrophe:
                    # Plural possessive ("users'") or contraction ("don't") outside quotes
                    chars.append(ch if not in_double else ' ')
                else:
                    # Opening single quote
                    in_single = True
                    chars.append(' ')
            else:
                if is_contraction:
                    # Contraction inside single quotes, e.g. 'don't'
                    chars.append(' ')
                else:
                    # Closing single quote
                    in_single = False
                    chars.append(' ')
        else:
            chars.append(' ' if (in_double or in_single) else ch)
    out = "".join(chars).strip()
    return out if out else s


def _has_command_in_quotes_only(message: str) -> bool:
    """True when task creation phrases only appear inside quotes in a conversational message."""
    msg = (message or "")[:2000].strip()
    unquoted = _strip_quoted_text(msg)
    if unquoted == msg:
        return False
    has_in_orig = bool(_CREATION_PHRASE.search(msg) or re.search(r"\bremind me\b", msg, re.IGNORECASE))
    has_in_unquoted = bool(_CREATION_PHRASE.search(unquoted) or re.search(r"\bremind me\b", unquoted, re.IGNORECASE))
    return has_in_orig and not has_in_unquoted


def _get_leading_words(msg: str) -> list[str]:
    clean = msg.strip().lower()
    for greeting in ("hey", "hi", "hello", "ok", "okay"):
        if clean.startswith(greeting):
            rem = clean[len(greeting):].lstrip(" ,!:")
            if rem:
                clean = rem
            break
    return [w.rstrip(",:;?!'\"") for w in clean.split() if w.rstrip(",:;?!'\"")]


def _has_non_command_lead(msg: str) -> bool:
    words = _get_leading_words(msg)
    if not words:
        return False
    first = words[0]
    if first in ("did", "should", "is", "are", "am", "was", "were", "why", "how", "what", "what's", "whats", "when", "where", "who", "which", "kya", "kaise", "kyun"):
        return True
    if first in ("do", "does"):
        if len(words) > 1 and words[1] in ("you", "u", "i", "we", "they", "it", "this", "that", "compass"):
            return True
    if first in ("can", "could", "would", "will"):
        if len(words) > 1 and words[1] in ("i", "we", "it", "they"):
            return True
    return False


def is_question_framed(message: str) -> bool:
    """True when the message reads as a question: trailing '?' or an interrogative lead."""
    msg = (message or "")[:2000].strip().lower()
    if not msg:
        return False
    if msg.endswith("?"):
        return True
    words = _get_leading_words(msg)
    if words and words[0] in INTERROGATIVE_LEADS:
        return True
    return bool(_PRONOUN_LEAD.match(msg) or _WH_LEAD.match(msg))


def mentions_task_creation(message: str) -> bool:
    """True when the message talks about adding/creating/scheduling tasks or deadlines."""
    raw = (message or "")[:2000]
    if _has_command_in_quotes_only(raw):
        return False
    msg = normalize_task_intent_text(raw)
    unquoted = _strip_quoted_text(msg)
    return bool(_CREATION_PHRASE.search(unquoted or ""))


def has_explicit_task_phrase(message: str) -> bool:
    """The user literally asked to add/remind/schedule something, as opposed to the model inferring it."""
    raw = (message or "")[:2000]
    if _has_command_in_quotes_only(raw):
        return False
    msg = normalize_task_intent_text(raw)
    unquoted = _strip_quoted_text(msg)
    return mentions_task_creation(unquoted) or bool(re.search(r"\bremind me\b", unquoted or "", re.IGNORECASE))


def strict_command_title(message: str) -> str:
    """Title captured from what follows the creation phrase; '' when there is none."""
    from backend.router_helpers import _extract_task_creation_args

    raw = (message or "")[:2000]
    if _has_command_in_quotes_only(raw) or _has_non_command_lead(raw):
        return ""
    msg = normalize_task_intent_text(raw)
    if _has_non_command_lead(msg):
        return ""
    text = _POLITE_PREFIX.sub("", msg.strip().rstrip("?").strip())
    return _extract_task_creation_args(text).get("title", "") or ""


def title_problem(title: Optional[str]) -> Optional[str]:
    """Why a title cannot be used (None when it is a meaningful task name)."""
    clean = (title or "").strip()
    if not clean:
        return "empty"
    if len(clean) > MAX_TITLE_LEN:
        return "too_long"
    if "?" in clean or _TITLE_QUESTION_LEAD.match(clean.lower()):
        return "question_like"
    words = re.findall(r"[A-Za-z0-9']+", clean.lower())
    if not any(re.search(r"[A-Za-z]", w) for w in words):
        return "no_words"
    if all(w in _FILLER_WORDS for w in words):
        return "filler_only"
    return None


def classify_task_message(message: str) -> str:
    """STATEMENT (not a question), COMMAND (question-framed but concrete) or QUESTION."""
    raw = (message or "")[:2000].strip()
    if _has_command_in_quotes_only(raw) or _has_non_command_lead(raw):
        return QUESTION
    msg = normalize_task_intent_text(raw)
    if _has_non_command_lead(msg):
        return QUESTION
    if not is_question_framed(raw) and not is_question_framed(msg):
        return STATEMENT
    return COMMAND if title_problem(strict_command_title(raw)) is None else QUESTION


def blocks_task_creation(message: str) -> bool:
    """True when a message must not create a task: it is a question without a concrete task."""
    raw = (message or "")[:2000].strip()
    if _has_command_in_quotes_only(raw) or _has_non_command_lead(raw):
        return True
    msg = normalize_task_intent_text(raw)
    if _has_non_command_lead(msg):
        return True
    return classify_task_message(raw) == QUESTION


def is_capability_question(message: str) -> bool:
    """A question about adding tasks/deadlines (answered conversationally, never executed)."""
    return blocks_task_creation(message) and mentions_task_creation(message)


def is_intake_intent(message: str) -> bool:
    """Messages handled deterministically before any model call: pasted task lists or capability asks."""
    from backend.services.task_intake_llm import looks_like_prose_task_list
    from backend.services.task_intake_parse import parse_task_list

    return (
        is_capability_question(message)
        or parse_task_list(message) is not None
        or looks_like_prose_task_list(message)
    )
