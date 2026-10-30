"""Audit tests for PR #219: Regex catastrophic backtracking / ReDoS safety."""

import time

from backend.services.task_intent import _CREATION_PHRASE


def test_creation_phrase_regex_redos_under_100ms():
    """Bug: _CREATION_PHRASE regex uses .* with re.DOTALL between verbs and nouns.

    On a 50,000-character input of repeated 'add ', it backtracks catastrophically
    and takes over 9,000 ms, violating CodeQL polynomial regex limits (<100 ms).
    """
    adversarial_input = "add " * 12500  # 50,000 characters
    start = time.perf_counter()
    _ = _CREATION_PHRASE.search(adversarial_input)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 100, f"_CREATION_PHRASE took {elapsed_ms:.1f}ms on 50k chars (must be <100ms)"


def test_creation_phrase_regex_create_redos_under_100ms():
    """Bug: _CREATION_PHRASE regex on repeated 'create ' words backtracks catastrophically."""
    adversarial_input = "create " * 7500  # ~52,500 characters
    start = time.perf_counter()
    _ = _CREATION_PHRASE.search(adversarial_input)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 100, f"_CREATION_PHRASE took {elapsed_ms:.1f}ms on 'create ' (must be <100ms)"
