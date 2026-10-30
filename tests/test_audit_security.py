"""Audit tests for PR #219: Security configurations and hardcoded secrets."""

import pytest
from backend.config import Settings


def test_backend_config_has_no_hardcoded_fallback_edge_hmac_secret():
    """Bug: backend/config.py line 61 defines a 36-character hardcoded default fallback

    for EDGE_HMAC_SECRET ('compass_...'). If EDGE_HMAC_SECRET is unset in the environment,
    the backend falls back to this hardcoded secret instead of failing closed.
    """
    field_default = Settings.model_fields["EDGE_HMAC_SECRET"].default
    secret_len = len(field_default) if isinstance(field_default, str) else 0

    assert secret_len == 0, f"backend/config.py has hardcoded EDGE_HMAC_SECRET fallback of length {secret_len}"


def test_backend_production_fail_closed_when_edge_hmac_secret_unset():
    """In production mode, if EDGE_HMAC_SECRET is unset, the backend must fail closed."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        AUTH_TOKEN="real-production-secret-token-12345",
        TOKEN_ENCRYPTION_KEY="custom-secure-prod-encryption-key-32b!",
        GUEST_SIGNING_SECRET="custom-secure-prod-guest-secret-32b!",
        EDGE_HMAC_SECRET="",
    )
    assert prod_settings.is_production()
    with pytest.raises((RuntimeError, ValueError), match=r"EDGE_HMAC_SECRET"):
        prod_settings.validate_production_secrets()
    with pytest.raises(RuntimeError, match=r"EDGE_HMAC_SECRET"):
        prod_settings.validate_edge_hmac_secret()


def test_backend_non_production_uses_random_per_process_edge_secret():
    """In non-production mode, an unset EDGE_HMAC_SECRET falls back to a per-process random secret."""
    dev_settings = Settings(ENVIRONMENT="development", EDGE_HMAC_SECRET="")
    assert not dev_settings.is_production()
    assert len(dev_settings.EDGE_HMAC_SECRET) == 64
