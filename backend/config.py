"""
Compass — Application configuration.

Uses pydantic-settings to load from environment variables and .env file.
All model IDs, database URLs, and auth tokens are configured here.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Any
import secrets
from pydantic import field_validator, model_validator

_PER_PROCESS_DEV_EDGE_SECRET: str = secrets.token_hex(32)
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_PROTECTED_DB_HOSTS: tuple[str, ...] = ("ep-sweet-fire-b2y9w95z",)
PROTECTED_DB_HOSTS: tuple[str, ...] = DEFAULT_PROTECTED_DB_HOSTS


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # --- Database ---
    DATABASE_URL: str = "postgresql://compass:compass@localhost:5432/compass"
    DATABASE_URL_UNPOOLED: str = ""
    TEST_DATABASE_URL: str = ""
    PROTECTED_DB_HOSTS: str = "ep-sweet-fire-b2y9w95z"  # Comma-separated list of protected endpoint IDs / hostnames

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

    # --- Output Token Budgets & Response Lifecycles ---
    MAX_DEFAULT_OUTPUT_TOKENS: int = 4096
    MAX_SYNTHESIS_TOKENS: int = 8192
    MAX_REASONING_TOKENS: int = 4096
    MAX_CONTINUATION_ATTEMPTS: int = 2

    # --- Environment & Security ---
    ENVIRONMENT: str = "production"  # development | test | production (must be explicitly 'development' to expose docs)
    ENABLE_DEMO_SEEDING: bool = False  # Disabled by default; enabled only via explicit environment variable
    GLOBAL_DAILY_DEMO_SEED_CAP: int = 300  # Global daily cap on persona-seeded identities
    DEFAULT_DEV_TOKEN: str = "dev-token"
    DEFAULT_DEV_ENCRYPTION_KEY: str = "compass_secure_local_dev_token_encryption_key_32bytes!"

    # --- Proxy & IP Resolution ---
    # Path: Vercel rewrite -> Render (2 hops: Render is hop 1, Vercel is hop 2)
    TRUSTED_PROXY_HOPS: int = 1
    TRUST_CF_CONNECTING_IP: bool = True
    TRUST_TRUE_CLIENT_IP: bool = False
    TRUSTED_PROXY_CIDR_RESOLUTION: bool = False
    EDGE_HMAC_SECRET: str = ""
    VERCEL_EDGE_SECRET: str | None = None

    # --- Rate Limiter & Abuse Protection ---
    RATE_LIMIT_FAIL_CLOSED: bool = True
    GLOBAL_DAILY_TAVILY_CREDIT_CAP: int = 100
    GLOBAL_DAILY_MODEL_CALL_CAP: int = 1000
    GLOBAL_DAILY_MINT_CAP: int = 200
    COMPASS_KILL_SWITCH_ACTIVE: bool = False
    # Per-identity daily Tavily credit limits (env: TAVILY_DAILY_GUEST_CREDITS / TAVILY_DAILY_USER_CREDITS).
    # Values < 1 or non-integers fall back to the default with a warning; the cap can never be disabled.
    TAVILY_DAILY_GUEST_CREDITS: int = 25
    TAVILY_DAILY_USER_CREDITS: int = 30

    # --- Pinned Authority Domains & Event Prefixes ---
    PINNED_TIER_1_DOMAINS: list[str] = [
        "docs.nebius.com",
        "nebius.com",
        "studio.nebius.ai",
        "api.tokenfactory.nebius.com",
    ]
    PINNED_EVENT_PREFIXES: list[str] = []

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
    TAVILY_ENABLED: bool = False  # Disabled pending explicit team sign-off
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

    def is_test(self) -> bool:
        """Check if running in test environment."""
        return self.ENVIRONMENT.lower() in ("test", "testing")

    def is_staging(self) -> bool:
        """Check if running in staging environment."""
        return self.ENVIRONMENT.lower() in ("staging", "stage")

    def is_production(self) -> bool:
        """Check if running in production or staging mode for security controls, or fail-closed when unset."""
        env = (getattr(self, "ENVIRONMENT", "") or "").lower().strip()
        if not env:
            return True  # Fail-closed default: unset behaves as production
        return env in ("production", "prod", "staging", "stage") or (
            bool(os.environ.get("RENDER")) and env not in ("development", "test", "testing")
        )

    @model_validator(mode="after")
    def _resolve_edge_hmac_secret(self) -> "Settings":
        if not self.is_production():
            if not (self.EDGE_HMAC_SECRET or self.VERCEL_EDGE_SECRET):
                self.EDGE_HMAC_SECRET = _PER_PROCESS_DEV_EDGE_SECRET
        return self

    def validate_edge_hmac_secret(self) -> None:
        """Startup guard: fail closed if EDGE_HMAC_SECRET is unset in production."""
        if self.is_production():
            effective = (self.EDGE_HMAC_SECRET or self.VERCEL_EDGE_SECRET or "").strip()
            if not effective or effective in ("dev-secret", "test-secret", "compass_vercel_edge_hmac_secret_2026"):
                raise RuntimeError("STARTUP REFUSED: EDGE_HMAC_SECRET environment variable is missing in production")

    def get_missing_production_secrets(self) -> tuple[list[str], list[str]]:
        """Return (missing_secret_names, duplicate_secret_names) for production configuration without exposing secret values."""
        if not self.is_production():
            return [], []

        missing = []
        if not self.AUTH_TOKEN or self.AUTH_TOKEN.strip() in (self.DEFAULT_DEV_TOKEN, "compass-token", "test-token"):
            missing.append("AUTH_TOKEN")
        if not self.TOKEN_ENCRYPTION_KEY or self.TOKEN_ENCRYPTION_KEY.strip() == self.DEFAULT_DEV_ENCRYPTION_KEY:
            missing.append("TOKEN_ENCRYPTION_KEY")
        if not self.GUEST_SIGNING_SECRET or self.GUEST_SIGNING_SECRET.strip() in ("dev-secret", "test-secret", "compass-guest-token-secret-2026"):
            missing.append("GUEST_SIGNING_SECRET")
        effective_edge_secret = (self.EDGE_HMAC_SECRET or self.VERCEL_EDGE_SECRET or "").strip()
        if not effective_edge_secret or effective_edge_secret in ("dev-secret", "test-secret", "compass_vercel_edge_hmac_secret_2026"):
            missing.append("EDGE_HMAC_SECRET")

        secrets_dict = {
            "AUTH_TOKEN": self.AUTH_TOKEN.strip() if self.AUTH_TOKEN else "",
            "TOKEN_ENCRYPTION_KEY": self.TOKEN_ENCRYPTION_KEY.strip() if self.TOKEN_ENCRYPTION_KEY else "",
            "GUEST_SIGNING_SECRET": self.GUEST_SIGNING_SECRET.strip() if self.GUEST_SIGNING_SECRET else "",
            "EDGE_HMAC_SECRET": effective_edge_secret,
        }

        # Check for duplicates among configured non-empty secrets
        duplicates = []
        seen: dict[str, str] = {}
        for name, val in secrets_dict.items():
            if not val or name in missing:
                continue
            if val in seen:
                duplicates.append(f"{seen[val]} == {name}")
            else:
                seen[val] = name

        return missing, duplicates

    def validate_production_secrets(self) -> None:
        """Validate that required production secrets are set, secure, and not reused."""
        if not self.is_production():
            return

        missing, duplicates = self.get_missing_production_secrets()
        errors = []
        if missing:
            errors.append(f"Missing or default required secrets: {', '.join(missing)}")
        if duplicates:
            errors.append(f"Secret reuse detected: {', '.join(duplicates)}")

        if errors:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: "
                + "; ".join(errors)
                + "\nAll 4 secrets (AUTH_TOKEN, GUEST_SIGNING_SECRET, EDGE_HMAC_SECRET, TOKEN_ENCRYPTION_KEY) "
                "must be independently generated with strong random values (e.g. `openssl rand -hex 32`)."
            )

    def get_masked_database_url(self) -> str:
        """Return DATABASE_URL with password masked for safe logging."""
        if not self.DATABASE_URL:
            return "NOT CONFIGURED"
        try:
            import urllib.parse
            p = urllib.parse.urlparse(self.DATABASE_URL)
            user = p.username or ""
            host = p.hostname or "unknown"
            port = f":{p.port}" if p.port else ""
            path = p.path or ""
            return f"{p.scheme}://{user}:***@{host}{port}{path}"
        except Exception:
            return "INVALID_DATABASE_URL"

    def validate_database_target(self) -> None:
        """Startup guard: refuse to start when DATABASE_URL, DATABASE_URL_UNPOOLED,
        TEST_DATABASE_URL, or any other *_DATABASE_URL* env var matches any entry in
        PROTECTED_DB_HOSTS and the process is not running on Render (no RENDER env var),
        regardless of ENVIRONMENT (including unset).
        TEST_DATABASE_URL must NEVER point to a protected host even on Render."""
        protected = [h.strip().lower() for h in self.PROTECTED_DB_HOSTS.split(",") if h.strip()]
        if not protected:
            return

        import urllib.parse
        is_render = bool(os.environ.get("RENDER"))

        urls_to_check: list[tuple[str, str]] = []
        if self.DATABASE_URL:
            urls_to_check.append(("DATABASE_URL", self.DATABASE_URL))
        if getattr(self, "DATABASE_URL_UNPOOLED", None):
            urls_to_check.append(("DATABASE_URL_UNPOOLED", self.DATABASE_URL_UNPOOLED))
        if getattr(self, "TEST_DATABASE_URL", None):
            urls_to_check.append(("TEST_DATABASE_URL", self.TEST_DATABASE_URL))

        for k, v in os.environ.items():
            if "DATABASE_URL" in k.upper() and k not in [x[0] for x in urls_to_check]:
                urls_to_check.append((k, v))

        for var_name, url_val in urls_to_check:
            if not url_val or not isinstance(url_val, str):
                continue
            try:
                p = urllib.parse.urlparse(url_val)
                host = (p.hostname or "").lower()
            except Exception:
                continue

            for prot in protected:
                if prot in host:
                    if "TEST" in var_name.upper():
                        raise RuntimeError(
                            f"STARTUP REFUSED: {var_name} targets protected database host '{host}' matching '{prot}'. "
                            f"Test database URLs must NEVER point to protected hosts, even in CI/Render environments."
                        )
                    if not is_render:
                        raise RuntimeError(
                            f"STARTUP REFUSED: {var_name} targets protected database host '{host}' matching '{prot}'. "
                            f"Local development, testing, or non-Render execution must use an isolated development database branch."
                        )

    def get_masked_database_hosts(self) -> dict[str, str]:
        """Return masked hostnames for all configured database URLs."""
        import urllib.parse
        masked: dict[str, str] = {}
        urls: list[tuple[str, str]] = [
            ("DATABASE_URL", self.DATABASE_URL),
            ("DATABASE_URL_UNPOOLED", getattr(self, "DATABASE_URL_UNPOOLED", "")),
            ("TEST_DATABASE_URL", getattr(self, "TEST_DATABASE_URL", "")),
        ]
        for k, v in os.environ.items():
            if "DATABASE_URL" in k.upper() and k not in [x[0] for x in urls]:
                urls.append((k, v))
        for name, val in urls:
            if not val:
                masked[name] = "<not set>"
                continue
            try:
                p = urllib.parse.urlparse(val)
                h = p.hostname or "unknown"
                if len(h) > 8:
                    masked[name] = f"{h[:4]}...{h[-4:]}"
                else:
                    masked[name] = "***"
            except Exception:
                masked[name] = "<invalid>"
        return masked

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

    @field_validator("TAVILY_DAILY_GUEST_CREDITS", "TAVILY_DAILY_USER_CREDITS", mode="before")
    @classmethod
    def parse_tavily_daily_credits(cls, v: Any, info: Any) -> int:
        default = cls.model_fields[info.field_name].default
        try:
            if isinstance(v, bool):
                raise ValueError("bool is not an integer")
            if isinstance(v, float) and not v.is_integer():
                raise ValueError("non-integer")
            parsed = int(str(v).strip()) if isinstance(v, str) else int(v)
            if parsed < 1:
                raise ValueError("must be >= 1")
            return parsed
        except (TypeError, ValueError):
            logging.getLogger("compass.config").warning(
                "Invalid %s=%r (must be an integer >= 1); falling back to default %d",
                info.field_name, v, default,
            )
            return default

    @field_validator("ENABLE_DEMO_SEEDING", mode="before")
    @classmethod
    def parse_enable_demo_seeding(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            val = v.strip().lower()
            if val in ("true", "1", "yes", "on", "t"):
                return True
            if val in ("false", "0", "no", "off", "f", ""):
                return False
        return bool(v)

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
