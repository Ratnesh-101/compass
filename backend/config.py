"""
Compass — Application configuration.

Uses pydantic-settings to load from environment variables and .env file.
All model IDs, database URLs, and auth tokens are configured here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # --- Database ---
    DATABASE_URL: str = "postgresql://compass:compass@localhost:5432/compass"

    # --- Nebius Token Factory ---
    NEBIUS_API_KEY: str = ""  # Required — set in .env
    NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1/"

    # --- Model IDs ---
    ROUTER_MODEL: str = "nvidia/Nemotron-3-Nano-8B-v1"
    SKILL_MODEL: str = "nvidia/nemotron-3-super-49b-v1"
    SYNTHESIS_MODEL: str = "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1"
    EMBEDDING_MODEL: str = "BAAI/bge-en-icl"
    EMBEDDING_DIMENSION: int = 768

    # --- Auth ---
    AUTH_TOKEN: str = ""  # Required — set in .env

    # --- App ---
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # --- Cost tracking (USD per 1M tokens, approximate) ---
    COST_PER_1M_INPUT: dict[str, float] = {
        "nvidia/Nemotron-3-Nano-8B-v1": 0.12,
        "nvidia/nemotron-3-super-49b-v1": 0.40,
        "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1": 3.00,
        "BAAI/bge-en-icl": 0.05,
    }
    COST_PER_1M_OUTPUT: dict[str, float] = {
        "nvidia/Nemotron-3-Nano-8B-v1": 0.12,
        "nvidia/nemotron-3-super-49b-v1": 0.40,
        "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1": 3.00,
    }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Use this instead of a module-level global
    so the import doesn't crash when .env is missing (e.g. during tests)."""
    return Settings()
