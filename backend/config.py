"""
Compass — Application configuration.

Uses pydantic-settings to load from environment variables and .env file.
All model IDs, database URLs, and auth tokens are configured here.
"""

import json
from functools import lru_cache
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # --- Database ---
    DATABASE_URL: str = "postgresql://compass:compass@localhost:5432/compass"

    # --- Nebius Token Factory ---
    NEBIUS_API_KEY: str = ""  # Required — set in .env
    NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1/"

    # --- Model IDs ---
    ROUTER_MODEL: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    SKILL_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    REASONING_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    SYNTHESIS_MODEL: str = "nvidia/Nemotron-3-Ultra-550b-a55b"
    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-8B"
    EMBEDDING_DIMENSION: int = 768

    # --- Environment & Security ---
    ENVIRONMENT: str = "production"  # development | test | production (must be explicitly 'development' to expose docs)
    DEFAULT_DEV_TOKEN: str = "dev-token"
    DEFAULT_DEV_ENCRYPTION_KEY: str = "compass_secure_local_dev_token_encryption_key_32bytes!"

    # --- Proxy & IP Resolution ---
    # Path: Vercel rewrite -> Render (2 hops: Render is hop 1, Vercel is hop 2)
    TRUSTED_PROXY_HOPS: int = 1
    TRUST_CF_CONNECTING_IP: bool = False
    TRUST_TRUE_CLIENT_IP: bool = False
    EDGE_HMAC_SECRET: str = "compass_vercel_edge_hmac_secret_2026"
    VERCEL_EDGE_SECRET: str = "compass_vercel_edge_hmac_secret_2026"

    # --- Rate Limiter & Abuse Protection ---
    RATE_LIMIT_FAIL_CLOSED: bool = True
    GLOBAL_DAILY_TAVILY_CREDIT_CAP: int = 100
    GLOBAL_DAILY_MODEL_CALL_CAP: int = 1000
    GLOBAL_DAILY_MINT_CAP: int = 200
    COMPASS_KILL_SWITCH_ACTIVE: bool = False
    TRUST_CF_CONNECTING_IP: bool = True
    TRUSTED_PROXY_HOPS: int = 1

    # --- Pinned Authority Domains & Event Prefixes ---
    PINNED_TIER_1_DOMAINS: list[str] = [
        "docs.nebius.com",
        "nebius.com",
        "studio.nebius.ai",
        "api.tokenfactory.nebius.com",
    ]
    PINNED_EVENT_PREFIXES: list[str] = [
        "https://nebiusglobalaihackathon.devpost.com",
        "http://nebiusglobalaihackathon.devpost.com",
        "nebiusglobalaihackathon.devpost.com",
        "https://nebius-hackathon.devpost.com",
        "http://nebius-hackathon.devpost.com",
        "nebius-hackathon.devpost.com",
    ]

    # --- Auth ---
    AUTH_TOKEN: str = ""  # Required — set in .env

    # --- Guest / Anonymous Mode ---
    GUEST_MAX_CONVERSATIONS: int = 50
    GUEST_MAX_MESSAGES_PER_CONVERSATION: int = 200
    GUEST_MAX_MEMORIES: int = 100
    GUEST_RETENTION_DAYS: int = 30
    GUEST_RATE_LIMIT: int = 30
    GUEST_MINT_HOURLY_IP_LIMIT: int = 5
    GUEST_SIGNING_SECRET: str = ""

    # --- Tavily Search API ---
    TAVILY_API_KEY: str = ""
    TAVILY_ENABLED: bool = True  # MUST be True in the submitted build
    TAVILY_ABSTAIN_FIRST: bool = True
    TAVILY_SEARCH_DEPTH: str = "basic"  # ultra-fast | fast | basic | advanced
    TAVILY_MAX_RESULTS: int = 5
    TAVILY_TIMEOUT_S: float = 12.0

    # --- Google Calendar OAuth ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "https://compass-farmlytics.vercel.app/api/calendar/callback"
    TOKEN_ENCRYPTION_KEY: str = "compass_secure_local_dev_token_encryption_key_32bytes!"

    # --- App ---
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000

    def is_development(self) -> bool:
        """Check if explicitly running in development mode."""
        return self.ENVIRONMENT.lower() == "development"

    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT.lower() in ("production", "prod")

    def validate_production_secrets(self) -> None:
        """Validate that insecure dev-default secrets are not used in production."""
        if not self.is_production():
            return

        if not self.AUTH_TOKEN or self.AUTH_TOKEN.strip() in (self.DEFAULT_DEV_TOKEN, "compass-token", "test-token"):
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: AUTH_TOKEN must be securely configured in production "
                "and cannot use default development tokens ('dev-token')."
            )

        if not self.TOKEN_ENCRYPTION_KEY or self.TOKEN_ENCRYPTION_KEY.strip() == self.DEFAULT_DEV_ENCRYPTION_KEY:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: TOKEN_ENCRYPTION_KEY must be securely configured in production "
                "and cannot use the default development encryption key."
            )

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:80",
        "http://localhost",
        "https://compass-kappa-nine.vercel.app",
        "https://compass-farmlytics.vercel.app",
        "https://compass-frontend.vercel.app",
        "https://compass.nebius.app",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(item).strip() for item in v if item]
        if isinstance(v, str):
            val = v.strip()
            if val.startswith("[") and val.endswith("]"):
                try:
                    loaded = json.loads(val)
                    if isinstance(loaded, list):
                        return [str(item).strip() for item in loaded if item]
                except Exception:
                    val = val[1:-1]
            return [orig.strip().strip("'\"") for orig in val.split(",") if orig.strip()]
        return []

    # --- Cost tracking (USD per 1M tokens, verified Nebius Token Factory rates) ---
    COST_PER_1M_INPUT: dict[str, float] = {
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.06,
        "nvidia/nemotron-3-super-120b-a12b": 0.30,
        "nvidia/Nemotron-3-Ultra-550b-a55b": 0.80,
        "Qwen/Qwen3-Embedding-8B": 0.02,
    }
    COST_PER_1M_OUTPUT: dict[str, float] = {
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.24,
        "nvidia/nemotron-3-super-120b-a12b": 0.90,
        "nvidia/Nemotron-3-Ultra-550b-a55b": 2.40,
        "Qwen/Qwen3-Embedding-8B": 0.00,
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
