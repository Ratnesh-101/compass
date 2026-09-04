"""
Compass — Nebius Vector Factory Service.

Generates 768-dimensional vector embeddings via Nebius Token Factory (OpenAI-compatible SDK)
using Matryoshka dimension truncation and L2 normalization for pgvector HNSW indexing.
"""

import os
import math
import asyncio
import logging
from typing import List
from openai import OpenAI, AsyncOpenAI
from backend.config import get_settings

logger = logging.getLogger("compass.services.embeddings")
settings = get_settings()

TARGET_MODEL = "Qwen/Qwen3-Embedding-8B"
DIMENSION = 768


def _get_base_url() -> str:
    # Prefer explicit NEBIUS_BASE_URL or default to Nebius API endpoint
    return os.getenv("NEBIUS_BASE_URL") or getattr(settings, "NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1/")


def _get_api_key() -> str:
    return os.getenv("NEBIUS_API_KEY") or getattr(settings, "NEBIUS_API_KEY", "")


def _generate_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """Deterministic pseudo-random 768-element unit-normalized float vector fallback."""
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(text))
    raw = [math.sin(seed + i * 0.17) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [round(x / norm, 6) for x in raw]


def _normalize_vector(vec: List[float], dim: int = 768) -> List[float]:
    """Truncate to exact dimensions and L2-normalize for pgvector HNSW cosine ops."""
    truncated = vec[:dim]
    norm = math.sqrt(sum(x * x for x in truncated)) or 1.0
    return [round(x / norm, 6) for x in truncated]


async def get_embedding(text: str) -> List[float]:
    """Generate a 768-dimensional normalized embedding via Nebius Token Factory.

    Truncates array to exactly 768 dimensions (Matryoshka representation)
    and L2-normalizes to adhere to pgvector HNSW index constraints.
    """
    api_key = _get_api_key()
    base_url = _get_base_url()
    model_name = getattr(settings, "EMBEDDING_MODEL", TARGET_MODEL) or TARGET_MODEL

    if api_key:
        try:
            # Using AsyncOpenAI with 8.0s timeout safeguard
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=8.0)
            resp = await client.embeddings.create(
                model=model_name,
                input=text,
                dimensions=DIMENSION,
            )
            raw_vec = resp.data[0].embedding
            return _normalize_vector(raw_vec, DIMENSION)
        except Exception as e:
            logger.warning(f"Async Nebius embedding call failed ({e}). Attempting sync client or fallback.")
            try:
                sync_client = OpenAI(api_key=api_key, base_url=base_url, timeout=8.0)
                resp = await asyncio.to_thread(
                    sync_client.embeddings.create,
                    model=model_name,
                    input=text,
                    dimensions=DIMENSION,
                )
                raw_vec = resp.data[0].embedding
                return _normalize_vector(raw_vec, DIMENSION)
            except Exception as sync_err:
                logger.error(f"Nebius Token Factory embedding error: {sync_err}. Using deterministic fallback.")

    return _generate_fallback_embedding(text, DIMENSION)


def get_embedding_sync(text: str) -> List[float]:
    """Synchronous version of get_embedding for background workers and sync callers."""
    api_key = _get_api_key()
    base_url = _get_base_url()
    model_name = getattr(settings, "EMBEDDING_MODEL", TARGET_MODEL) or TARGET_MODEL

    if api_key:
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=8.0)
            resp = client.embeddings.create(
                model=model_name,
                input=text,
                dimensions=DIMENSION,
            )
            raw_vec = resp.data[0].embedding
            return _normalize_vector(raw_vec, DIMENSION)
        except Exception as e:
            logger.error(f"Nebius sync embedding error: {e}. Using deterministic fallback.")

    return _generate_fallback_embedding(text, DIMENSION)
