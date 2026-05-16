"""Tests for vector store provider factory (no live DB, no OpenAI)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.config import AppSettings
from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_store import InMemoryVectorStore
from app.rag.vector_store_factory import (
    VectorStoreConfig,
    VectorStoreProviderName,
    build_vector_store_config_from_settings,
    create_vector_store,
)
from pydantic import ValidationError


def test_default_config_creates_in_memory_store() -> None:
    store = create_vector_store(VectorStoreConfig())
    assert isinstance(store, InMemoryVectorStore)


def test_provider_normalization() -> None:
    cfg = VectorStoreConfig(provider="  PGVECTOR  ", database_url="postgresql://u:p@localhost/db")
    assert cfg.normalized_provider() == "pgvector"
    assert cfg.to_provider_name() is VectorStoreProviderName.PGVECTOR


@pytest.mark.parametrize("dimensions", [0, -1])
def test_invalid_dimensions_rejected(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        VectorStoreConfig(dimensions=dimensions)


def test_pgvector_without_database_url_rejected() -> None:
    with pytest.raises(ValidationError, match="database_url is required"):
        VectorStoreConfig(provider="pgvector", database_url=None)


def test_pgvector_creates_pgvector_store_without_connecting() -> None:
    cfg = VectorStoreConfig(
        provider="pgvector",
        database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        table_name="rag_vector_records_16",
        dimensions=16,
    )
    store = create_vector_store(cfg)
    assert isinstance(store, PgVectorStore)
    assert store._table_name == "rag_vector_records_16"  # noqa: SLF001
    assert store._dimensions == 16  # noqa: SLF001


def test_unsupported_provider_raises_value_error() -> None:
    cfg = VectorStoreConfig(provider="pinecone")
    with pytest.raises(ValueError, match="Unsupported vector store provider"):
        create_vector_store(cfg)


def test_to_provider_name_invalid_returns_none() -> None:
    assert VectorStoreConfig(provider="weaviate").to_provider_name() is None


def test_build_vector_store_config_from_settings_maps_fields() -> None:
    settings = SimpleNamespace(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://u:p@localhost/db",
        pgvector_table="rag_vector_records_16",
        pgvector_dimensions=16,
    )
    cfg = build_vector_store_config_from_settings(settings)
    assert cfg.provider == "pgvector"
    assert cfg.database_url == "postgresql://u:p@localhost/db"
    assert cfg.table_name == "rag_vector_records_16"
    assert cfg.dimensions == 16


def test_app_settings_allows_pgvector_without_url() -> None:
    settings = AppSettings(vector_store_provider="pgvector", pgvector_database_url=None)
    assert settings.vector_store_provider == "pgvector"
    assert settings.pgvector_database_url is None


def test_settings_builder_then_factory_requires_url_for_pgvector() -> None:
    settings = AppSettings(vector_store_provider="pgvector", pgvector_database_url=None)
    with pytest.raises(ValidationError, match="database_url is required"):
        create_vector_store(build_vector_store_config_from_settings(settings))


def test_database_url_not_in_config_repr() -> None:
    cfg = VectorStoreConfig(
        provider="pgvector",
        database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    text = repr(cfg)
    assert "secret" not in text
    assert "postgresql://" not in text
