"""Tests for typed RetrievalConfig, profiles, and settings mapping."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.config import AppSettings, get_settings
from app.rag.config import (
    RetrievalConfig,
    RetrievalProfileName,
    build_retrieval_config_from_settings,
    retrieval_config_from_profile,
)
from app.rag.strategy import RetrievalStrategyName
from pydantic import ValidationError


def test_default_config_values() -> None:
    cfg = RetrievalConfig()
    assert cfg.strategy == "mock"
    assert cfg.embedding_provider == "mock"
    assert cfg.embedding_model == "mock-embedding-small"
    assert cfg.top_k == 5
    assert cfg.profile is None


def test_normalized_strategy_trims_and_lowercases() -> None:
    cfg = RetrievalConfig(strategy="  POLICY_ONLY  ")
    assert cfg.normalized_strategy() == "policy_only"


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("mock", RetrievalStrategyName.MOCK),
        ("semantic", RetrievalStrategyName.SEMANTIC),
        ("policy_only", RetrievalStrategyName.POLICY_ONLY),
        ("approved_examples", RetrievalStrategyName.APPROVED_EXAMPLES),
    ],
)
def test_to_strategy_name_valid(strategy: str, expected: RetrievalStrategyName) -> None:
    assert RetrievalConfig(strategy=strategy).to_strategy_name() == expected


@pytest.mark.parametrize("strategy", ["weaviate", "unknown", ""])
def test_to_strategy_name_invalid(strategy: str) -> None:
    assert RetrievalConfig(strategy=strategy).to_strategy_name() is None


@pytest.mark.parametrize("top_k", [0, -1])
def test_top_k_validation_rejects_non_positive(top_k: int) -> None:
    with pytest.raises(ValidationError):
        RetrievalConfig(top_k=top_k)


def test_profile_mock_resolves_to_mock_config() -> None:
    cfg = retrieval_config_from_profile(RetrievalProfileName.MOCK)
    assert cfg.strategy == "mock"
    assert cfg.top_k == 5
    assert cfg.embedding_provider == "mock"
    assert cfg.embedding_model == "mock-embedding-small"


def test_profile_policy_only_resolves_correctly() -> None:
    cfg = retrieval_config_from_profile("policy_only")
    assert cfg.strategy == "policy_only"
    assert cfg.to_strategy_name() == RetrievalStrategyName.POLICY_ONLY


def test_profile_approved_examples_resolves_correctly() -> None:
    cfg = retrieval_config_from_profile(RetrievalProfileName.APPROVED_EXAMPLES)
    assert cfg.strategy == "approved_examples"
    assert cfg.to_strategy_name() == RetrievalStrategyName.APPROVED_EXAMPLES


def test_profile_semantic_local_resolves_to_semantic_mock_embeddings() -> None:
    cfg = retrieval_config_from_profile(RetrievalProfileName.SEMANTIC_LOCAL)
    assert cfg.strategy == "semantic"
    assert cfg.embedding_provider == "mock"
    assert cfg.embedding_model == "mock-embedding-small"
    assert cfg.to_strategy_name() == RetrievalStrategyName.SEMANTIC
    assert cfg.vector_store_provider is None


def test_profile_semantic_pgvector_16_resolves_correctly() -> None:
    cfg = retrieval_config_from_profile(RetrievalProfileName.SEMANTIC_PGVECTOR_16)
    assert cfg.strategy == "semantic"
    assert cfg.top_k == 5
    assert cfg.embedding_provider == "mock"
    assert cfg.embedding_model == "mock-embedding-small"
    assert cfg.vector_store_provider == "pgvector"
    assert cfg.normalized_vector_store_provider() == "pgvector"
    assert cfg.to_strategy_name() == RetrievalStrategyName.SEMANTIC


def test_profile_semantic_pgvector_resolves_with_fallback_embeddings() -> None:
    cfg = retrieval_config_from_profile(
        RetrievalProfileName.SEMANTIC_PGVECTOR,
        fallback_embedding_provider="openai",
        fallback_embedding_model="text-embedding-3-small",
    )
    assert cfg.strategy == "semantic"
    assert cfg.top_k == 5
    assert cfg.embedding_provider == "openai"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.vector_store_provider == "pgvector"
    assert cfg.to_strategy_name() == RetrievalStrategyName.SEMANTIC


def test_build_retrieval_config_semantic_pgvector_from_settings() -> None:
    settings = SimpleNamespace(
        rag_profile="semantic_pgvector",
        rag_strategy="mock",
        rag_top_k=3,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://u:p@localhost/db",
        pgvector_table="rag_vector_records",
        pgvector_dimensions=1536,
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.profile == "semantic_pgvector"
    assert cfg.strategy == "semantic"
    assert cfg.embedding_provider == "openai"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.vector_store_provider == "pgvector"


def test_build_retrieval_config_semantic_pgvector_16_from_settings() -> None:
    settings = SimpleNamespace(
        rag_profile="semantic_pgvector_16",
        rag_strategy="mock",
        rag_top_k=3,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://u:p@localhost/db",
        pgvector_table="rag_vector_records_16",
        pgvector_dimensions=16,
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.profile == "semantic_pgvector_16"
    assert cfg.strategy == "semantic"
    assert cfg.vector_store_provider == "pgvector"


def test_profile_custom_uses_fallback_values() -> None:
    cfg = retrieval_config_from_profile(
        "custom",
        fallback_strategy="policy_only",
        fallback_top_k=2,
        fallback_embedding_provider="mock",
        fallback_embedding_model="custom-model",
    )
    assert cfg.strategy == "policy_only"
    assert cfg.top_k == 2
    assert cfg.embedding_model == "custom-model"


def test_unknown_profile_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported retrieval profile"):
        retrieval_config_from_profile("pinecone")


def test_build_retrieval_config_from_settings_uses_profile_when_set() -> None:
    settings = SimpleNamespace(
        rag_profile="semantic_local",
        rag_strategy="mock",
        rag_top_k=3,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.profile == "semantic_local"
    assert cfg.strategy == "semantic"
    assert cfg.top_k == 5


def test_build_retrieval_config_no_profile_preserves_existing_behavior() -> None:
    settings = SimpleNamespace(
        rag_profile=None,
        rag_strategy="semantic",
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        rag_top_k=3,
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.profile is None
    assert cfg.strategy == "semantic"
    assert cfg.top_k == 3


def test_build_retrieval_config_custom_profile_uses_env_fields() -> None:
    settings = SimpleNamespace(
        rag_profile="custom",
        rag_strategy="approved_examples",
        rag_top_k=2,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.profile == "custom"
    assert cfg.strategy == "approved_examples"
    assert cfg.top_k == 2


def test_build_retrieval_config_from_settings_maps_fields_without_profile() -> None:
    settings = SimpleNamespace(
        rag_strategy="semantic",
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        rag_top_k=3,
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.strategy == "semantic"
    assert cfg.top_k == 3
    assert cfg.to_strategy_name() == RetrievalStrategyName.SEMANTIC


def test_build_retrieval_config_missing_rag_top_k_defaults_to_five() -> None:
    settings = SimpleNamespace(
        rag_strategy="mock",
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    cfg = build_retrieval_config_from_settings(settings)
    assert cfg.top_k == 5


def test_app_settings_rag_top_k_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_TOP_K", raising=False)
    get_settings.cache_clear()
    assert AppSettings().rag_top_k == 5


def test_app_settings_rag_top_k_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_TOP_K", "2")
    get_settings.cache_clear()
    assert get_settings().rag_top_k == 2


def test_build_retrieval_config_from_settings_with_normalized_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PROFILE", " SEMANTIC_LOCAL ")
    get_settings.cache_clear()
    cfg = build_retrieval_config_from_settings(get_settings())
    assert cfg.profile == "semantic_local"
    assert cfg.strategy == "semantic"
