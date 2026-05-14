"""App settings: env / .env loading via pydantic-settings (no secret values asserted)."""

from __future__ import annotations

import pytest

from app.config import AppSettings, get_settings


def test_default_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """OS env wins over `.env`; pin LLM fields so expectations are stable in dev machines."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-vendor-ticket-drafter")
    settings = get_settings()
    assert isinstance(settings, AppSettings)
    assert settings.llm_provider == "mock"
    assert settings.llm_model == "mock-vendor-ticket-drafter"
    assert settings.app_name == "Inchand AI Commerce Operations Copilot"
    assert settings.environment == "development"


def test_environment_variable_override_llm_provider_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_* env vars map to AppSettings; do not print secrets."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-test-model")
    settings = get_settings()
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-test-model"
