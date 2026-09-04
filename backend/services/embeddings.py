"""
Compass — Nebius Vector Factory Service.

Connects to Nebius Token Factory via OpenAI-compatible SDK to generate
768-dimensional embeddings (Matryoshka representation) for pgvector HNSW indexing.
"""

import math
import logging
from typing import List
from openai import OpenAI
from backend.config import get_settings

logger = logging.getLogger("compass.services.embeddings")
settings = get_settings()

TARGET_MODEL = "Qwen/Qwen3-Embedding-8B"
DIMENSION = 768


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
    )


def _generate_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """Deterministic normalized 768-dim vector fallback when offline."""
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(text))
    raw = [math.sin(seed + i * 0.17) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def get_embedding(text: str) -> List[float]:
    """Generate a 768-dimensional embedding from Nebius Token Factory.
    
    Hard-locked to exactly 768 dimensions (Matryoshka representation) to match
    pgvector HNSW index constraints.
    """
    model_name = settings.EMBEDDING_MODEL or TARGET_MODEL

    if settings.NEBIUS_API_KEY:
        try:
            client = _get_client()
            resp = client.embeddings.create(
                model=model_name,
                input=text,
                dimensions=DIMENSION,  # Hard-locked 768-dim
                timeout=8.0,
            )

            vec = resp.data[0].embedding
            if len(vec) == DIMENSION:
                return vec
            logger.warning(f"Unexpected vector length {len(vec)}, truncating to {DIMENSION}")
            return vec[:DIMENSION]
        except Exception as e:
            logger.error(f"Nebius Token Factory embedding error: {e}. Using deterministic fallback.")

    return _generate_fallback_embedding(text, DIMENSION)
