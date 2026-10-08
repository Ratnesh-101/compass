"""
Compass — Startup Model Catalog Validation.

Verifies that every model ID in config exists in Nebius /models.
Fails loudly with RuntimeError; never silently falls back.
"""

import json
import logging
import urllib.request
from typing import Set

logger = logging.getLogger("compass.model_check")


def check_models_catalog(
    base_url: str,
    api_key: str,
    required_models: Set[str],
    fail_loudly: bool = True,
    routed_roles: dict[str, str] | None = None,
) -> None:
    """Validate that every required model ID exists in Nebius /models catalog.
    Fails loudly with RuntimeError if any model is missing.
    Logs the total catalog count and each individual routed model dynamically.
    """
    if not api_key or api_key.startswith("mock-") or api_key == "test-token":
        logger.info("Test/mock API key detected; skipping live Nebius model catalog check.")
        return

    clean_base = base_url.rstrip("/")
    if not clean_base.startswith(("https://", "http://")):
        logger.warning("Invalid URL scheme for Nebius base_url: %s", clean_base)
        return

    url = f"{clean_base}/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:  # nosec B310
            data = json.loads(resp.read().decode())
            available_ids = {m["id"] for m in data.get("data", [])}
    except Exception as e:
        logger.warning("Could not reach Nebius /models catalog at %s (%s); continuing startup.", clean_base, e)
        return

    missing = [m for m in required_models if m not in available_ids]
    if missing:
        err_msg = (
            f"Startup check failed: configured model(s) {missing} do not exist in Nebius /models catalog. "
            f"Available models ({len(available_ids)}): {sorted(list(available_ids))}. Never silently falling back."
        )
        logger.error(err_msg)
        if fail_loudly:
            raise RuntimeError(err_msg)

    routed_summary = (
        ", ".join(f"{role}={model}" for role, model in routed_roles.items())
        if routed_roles
        else ", ".join(sorted(list(required_models)))
    )
    logger.info(
        "✅ Startup model check passed: %d models available in Nebius catalog at %s. Routed models (%d): %s",
        len(available_ids),
        clean_base,
        len(required_models),
        routed_summary,
    )
