"""
Tests for startup model catalog validation (fail loudly, never silently fall back).
"""

import pytest
from unittest.mock import patch, MagicMock
from backend.services.model_check import check_models_catalog


def test_startup_check_fails_loudly_on_missing_model():
    """Missing model ID in Nebius /models catalog must raise RuntimeError."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"data": [{"id": "model-a"}, {"id": "model-b"}]}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError) as exc_info:
            check_models_catalog(
                base_url="https://api.tokenfactory.nebius.com/v1",
                api_key="valid-key",
                required_models={"model-a", "missing-model-c"},
                fail_loudly=True,
            )
        assert "Startup check failed" in str(exc_info.value)
        assert "missing-model-c" in str(exc_info.value)
        assert "Never silently falling back" in str(exc_info.value)


def test_startup_check_succeeds_when_all_models_present():
    """All configured models exist -> check completes without error."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-c"}]}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        check_models_catalog(
            base_url="https://api.tokenfactory.nebius.com/v1",
            api_key="valid-key",
            required_models={"model-a", "model-b"},
            fail_loudly=True,
        )


def test_startup_check_warns_and_continues_on_network_failure():
    """If the /models network request fails, log warning and continue without raising."""
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        # Must not raise RuntimeError
        check_models_catalog(
            base_url="https://api.tokenfactory.nebius.com/v1",
            api_key="valid-key",
            required_models={"model-a", "model-b"},
            fail_loudly=True,
        )

