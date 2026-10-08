"""
Compass — Persona Phrases API Router.

Exposes canonical signature phrase pools as a single source of truth for clients.
"""

from typing import Dict, List
import logging
from fastapi import APIRouter, Depends

from backend.dependencies import verify_token
from backend.persona import (
    STARTING_PHRASES,
    EXPLORING_PHRASES,
    RETURNING_PHRASES,
    MID_CHAT_PHRASES,
    CLOSING_PHRASES,
)

logger = logging.getLogger("compass.routers.persona")

router = APIRouter(prefix="/api/persona", tags=["persona"])


@router.get("/phrases")
async def get_persona_phrases(
    _token: str = Depends(verify_token),
) -> Dict[str, List[str]]:
    """Retrieve canonical signature phrase pools for thinking partner UI."""
    return {
        "starting_phrases": STARTING_PHRASES,
        "exploring_phrases": EXPLORING_PHRASES,
        "returning_phrases": RETURNING_PHRASES,
        "mid_chat_phrases": MID_CHAT_PHRASES,
        "closing_phrases": CLOSING_PHRASES,
    }
