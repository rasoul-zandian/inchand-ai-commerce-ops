"""App settings: env / .env loading via pydantic-settings (no secret values asserted)."""

from __future__ import annotations

import pytest
from app.config import AppSettings, get_settings
from pydantic import ValidationError


def test_default_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """OS env wins over `.env`; pin LLM fields so expectations are stable in dev machines."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-vendor-ticket-drafter")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_MODEL", "mock-embedding-small")
    settings = get_settings()
    assert isinstance(settings, AppSettings)
    assert settings.llm_provider == "mock"
    assert settings.llm_model == "mock-vendor-ticket-drafter"
    assert settings.app_name == "Inchand AI Commerce Operations Copilot"
    assert settings.environment == "development"
    assert settings.embedding_provider == "mock"
    assert settings.embedding_model == "mock-embedding-small"
    assert settings.rag_strategy == "mock"
    assert settings.rag_top_k == 5
    assert settings.show_full_iban_in_operator_console is True


def test_rag_strategy_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "policy_only")
    get_settings.cache_clear()
    assert get_settings().rag_strategy == "policy_only"


def test_environment_variable_override_llm_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_* env vars map to AppSettings; do not print secrets."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-test-model")
    settings = get_settings()
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-test-model"


def test_rag_profile_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_PROFILE", raising=False)
    get_settings.cache_clear()
    assert AppSettings().rag_profile is None


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_rag_profile_empty_or_whitespace_is_none(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("RAG_PROFILE", raw)
    get_settings.cache_clear()
    assert AppSettings().rag_profile is None


def test_rag_profile_normalized_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "SEMANTIC_LOCAL")
    get_settings.cache_clear()
    assert get_settings().rag_profile == "semantic_local"


def test_rag_profile_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", " policy_only ")
    get_settings.cache_clear()
    assert get_settings().rag_profile == "policy_only"


def test_invalid_rag_profile_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "pinecone")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="Invalid RAG_PROFILE"):
        AppSettings()


def test_rag_profile_semantic_pgvector_16_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_pgvector_16")
    get_settings.cache_clear()
    assert AppSettings().rag_profile == "semantic_pgvector_16"


def test_rag_profile_semantic_pgvector_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_pgvector")
    get_settings.cache_clear()
    assert AppSettings().rag_profile == "semantic_pgvector"


def test_invalid_rag_strategy_does_not_fail_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "weaviate")
    get_settings.cache_clear()
    assert get_settings().rag_strategy == "weaviate"
