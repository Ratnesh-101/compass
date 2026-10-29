"""
Compass — Nebius Vector Factory Service.

Generates 768-dimensional vector embeddings via Nebius Token Factory (OpenAI-compatible SDK)
using Matryoshka dimension truncation and L2 normalization for pgvector HNSW indexing.
"""

import os
import math
import asyncio
import logging
from typing import List, Optional
from openai import OpenAI, AsyncOpenAI
from backend.config import get_settings

logger = logging.getLogger("compass.services.embeddings")
settings = get_settings()

TARGET_MODEL = "Qwen/Qwen3-Embedding-8B"
DIMENSION = 768


def _get_base_url() -> str:
    # Prefer explicit NEBIUS_BASE_URL or default to Nebius API endpoint
    return str(os.getenv("NEBIUS_BASE_URL") or getattr(settings, "NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1/"))


def _get_api_key() -> str:
    return str(os.getenv("NEBIUS_API_KEY") or getattr(settings, "NEBIUS_API_KEY", ""))


_EMBEDDING_FAILURE_COUNT: int = 0


def get_embedding_failure_count() -> int:
    """Return total number of embedding generation failures encountered."""
    return _EMBEDDING_FAILURE_COUNT


def reset_embedding_failure_count() -> None:
    """Reset failure counter (primarily for test isolation)."""
    global _EMBEDDING_FAILURE_COUNT
    _EMBEDDING_FAILURE_COUNT = 0


def compute_historical_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """Deterministic formula used historically to produce pseudo-embeddings.

    NOTE: Must NEVER be written to memory_chunks or used for live vector search.
    Preserved strictly for forensic auditing and cleanup scripts to detect legacy rows.
    """
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(text))
    raw = [math.sin(seed + i * 0.17) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [round(x / norm, 6) for x in raw]


def is_historical_fallback_embedding(vec: List[float], text: str, dim: int = 768) -> bool:
    """Check whether a vector matches the historical synthetic fallback formula."""
    if not vec or len(vec) != dim:
        return False
    expected = compute_historical_fallback_embedding(text, dim)
    return all(abs(float(a) - float(b)) < 1e-4 for a, b in zip(vec, expected))


def _normalize_vector(vec: List[float], dim: int = 768) -> List[float]:
    """Truncate to exact dimensions and L2-normalize for pgvector HNSW cosine ops."""
    truncated = vec[:dim]
    norm = math.sqrt(sum(x * x for x in truncated)) or 1.0
    return [round(x / norm, 6) for x in truncated]


_async_client: Optional[AsyncOpenAI] = None


def _get_async_client(api_key: str, base_url: str) -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=8.0)
    return _async_client


async def get_embedding(text: str) -> Optional[List[float]]:
    """Generate a 768-dimensional normalized embedding via Nebius Token Factory.

    Truncates array to exactly 768 dimensions (Matryoshka representation)
    and L2-normalizes to adhere to pgvector HNSW index constraints.
    Returns None if the embedding API is unavailable or keys are unconfigured.
    """
    global _EMBEDDING_FAILURE_COUNT
    api_key = _get_api_key()
    base_url = _get_base_url()
    model_name = getattr(settings, "EMBEDDING_MODEL", TARGET_MODEL) or TARGET_MODEL

    if (
        api_key
        and not api_key.startswith("your_nebius")
        and api_key not in ("mock", "mock-key-not-used-in-tests")
        and getattr(settings, "ENVIRONMENT", "") != "test"
    ):
        try:
            client = _get_async_client(api_key, base_url)
            resp = await client.embeddings.create(
                model=model_name,
                input=text,
                dimensions=DIMENSION,
            )
            raw_vec = resp.data[0].embedding
            return _normalize_vector(raw_vec, DIMENSION)
        except Exception as e:
            logger.warning(f"Async Nebius embedding call failed ({e}). Attempting sync client.")
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
                logger.error(f"Nebius Token Factory embedding error: {sync_err}. Returning None.")

    _EMBEDDING_FAILURE_COUNT += 1
    logger.warning("Embedding service unavailable or key missing. Returning None (no synthetic vectors).")
    return None


def get_embedding_sync(text: str) -> Optional[List[float]]:
    """Synchronous version of get_embedding for background workers and sync callers.

    Returns None if embedding API is unavailable.
    """
    global _EMBEDDING_FAILURE_COUNT
    api_key = _get_api_key()
    base_url = _get_base_url()
    model_name = getattr(settings, "EMBEDDING_MODEL", TARGET_MODEL) or TARGET_MODEL

    if (
        api_key
        and not api_key.startswith("your_nebius")
        and api_key not in ("mock", "mock-key-not-used-in-tests")
        and getattr(settings, "ENVIRONMENT", "") != "test"
    ):
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
            logger.error(f"Nebius sync embedding error: {e}. Returning None.")

    _EMBEDDING_FAILURE_COUNT += 1
    logger.warning("Sync embedding unavailable. Returning None.")
    return None
