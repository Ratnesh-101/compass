"""Example-based intent check for tasks the model inferred from an implicit statement.

Same idea as semantic-router: a few labelled example utterances are embedded once (with the
embedding model Compass already uses) and a message is compared to both groups. It is used only to
stop the model from saving a task out of chatter ("I should probably start the project soon") and
never to block an explicit command. Any failure returns None, which callers treat as "allow".
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("compass.services.intent_gate")

TOP_K = 3
MARGIN = 0.04
RETRY_AFTER_FAILURE_S = 60.0

CREATE_TASK_EXAMPLES: Sequence[str] = (
    "add a task to submit the lab report by friday",
    "remind me to call the dentist tomorrow at 4",
    "create a deadline for the hackathon demo on november 3rd",
    "put dbms assignment 3 on my list due monday",
    "new task: revise operating systems notes",
    "schedule a reminder to email the professor tonight",
    "add finishing the devpost submission to my tasks for 10pm",
    "track the quiz prep as a task due in 3 days",
)
NOT_A_TASK_EXAMPLES: Sequence[str] = (
    "what is due this week",
    "how do I prepare for a hackathon",
    "i feel overwhelmed by all my deadlines",
    "explain what a deadlock is in operating systems",
    "can you plan my weekend",
    "i was thinking i should probably start the project soon",
    "thanks that helps",
    "which of my tasks is most urgent",
    "i have a quiz tomorrow and i am nervous",
    "tell me about your features",
    "my friend finished the assignment already",
    "should i prioritize the demo or the report",
)

Embedder = Callable[[str], Awaitable[Optional[List[float]]]]
_example_vectors: Optional[Dict[str, List[List[float]]]] = None
_failed_at: float = 0.0
_lock = asyncio.Lock()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def reset_cache() -> None:
    global _example_vectors, _failed_at
    _example_vectors, _failed_at = None, 0.0


async def _embed_all(texts: Sequence[str], embed: Embedder) -> Optional[List[List[float]]]:
    vectors = await asyncio.gather(*(embed(t) for t in texts), return_exceptions=True)
    return None if any(v is None or isinstance(v, BaseException) for v in vectors) else list(vectors)  # type: ignore[arg-type]


async def _examples(embed: Embedder) -> Optional[Dict[str, List[List[float]]]]:
    global _example_vectors, _failed_at
    if _example_vectors is not None:
        return _example_vectors
    if time.monotonic() - _failed_at < RETRY_AFTER_FAILURE_S:
        return None
    async with _lock:
        if _example_vectors is None:
            create = await _embed_all(CREATE_TASK_EXAMPLES, embed)
            other = await _embed_all(NOT_A_TASK_EXAMPLES, embed) if create else None
            if create and other:
                _example_vectors = {"create": create, "other": other}
            else:
                _failed_at = time.monotonic()
    return _example_vectors


def _group_score(vector: Sequence[float], group: List[List[float]]) -> float:
    top = sorted((_cosine(vector, g) for g in group), reverse=True)[:TOP_K]
    return sum(top) / len(top)


async def classify_task_intent(message: str, embed: Optional[Embedder] = None) -> Optional[bool]:
    """True = reads as a request to add a task, False = reads as something else, None = unknown."""
    try:
        if embed is None:
            from backend.config import get_settings
            from backend.services.embeddings import get_embedding as embed
            from backend.services.task_intake_llm import llm_available

            if not llm_available(get_settings().NEBIUS_API_KEY):
                return None
        examples = await _examples(embed)
        vector = await embed(message) if examples else None
        if not examples or not vector:
            return None
        create = _group_score(vector, examples["create"])
        other = _group_score(vector, examples["other"])
    except Exception as e:
        logger.warning("Intent gate unavailable (%s); allowing the model's choice", type(e).__name__)
        return None
    if abs(create - other) < MARGIN:
        return None
    return create > other
