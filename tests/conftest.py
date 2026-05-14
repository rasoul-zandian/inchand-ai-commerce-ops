"""Test isolation: reset cached settings and pin safe LLM defaults unless a test overrides them."""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear LRU cache between tests; default LLM to mock so `.env` cannot break the graph suite."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-vendor-ticket-drafter")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
