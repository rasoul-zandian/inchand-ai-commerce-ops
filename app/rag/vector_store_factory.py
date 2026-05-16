"""Vector store provider factory: memory or pgvector (no runtime wiring yet)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_store import InMemoryVectorStore, VectorStore


class VectorStoreProviderName(StrEnum):
    MEMORY = "memory"
    PGVECTOR = "pgvector"


class VectorStoreConfig(BaseModel):
    provider: str = "memory"
    database_url: str | None = Field(default=None, repr=False)
    table_name: str = "rag_vector_records"
    dimensions: int = 1536

    @field_validator("provider", "table_name", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _empty_database_url_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("dimensions")
    @classmethod
    def _dimensions_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("dimensions must be >= 1")
        return value

    @model_validator(mode="after")
    def _pgvector_requires_database_url(self) -> VectorStoreConfig:
        if self.normalized_provider() == VectorStoreProviderName.PGVECTOR.value:
            if self.database_url is None or not str(self.database_url).strip():
                raise ValueError("database_url is required when provider is pgvector")
        return self

    def normalized_provider(self) -> str:
        return self.provider.strip().lower()

    def to_provider_name(self) -> VectorStoreProviderName | None:
        try:
            return VectorStoreProviderName(self.normalized_provider())
        except ValueError:
            return None


def build_vector_store_config_from_settings(settings: Any) -> VectorStoreConfig:
    """Build ``VectorStoreConfig`` from ``AppSettings`` (or any object with the same fields)."""
    return VectorStoreConfig(
        provider=getattr(settings, "vector_store_provider", "memory"),
        database_url=getattr(settings, "pgvector_database_url", None),
        table_name=getattr(settings, "pgvector_table", "rag_vector_records"),
        dimensions=getattr(settings, "pgvector_dimensions", 1536),
    )


def create_vector_store(config: VectorStoreConfig) -> VectorStore:
    """Construct a ``VectorStore`` from validated config (no connection test)."""
    provider = config.to_provider_name()
    if provider is VectorStoreProviderName.MEMORY:
        return InMemoryVectorStore()
    if provider is VectorStoreProviderName.PGVECTOR:
        assert config.database_url is not None  # validated by VectorStoreConfig
        return PgVectorStore(
            config.database_url,
            table_name=config.table_name,
            dimensions=config.dimensions,
        )
    raise ValueError(f"Unsupported vector store provider: {config.provider!r}")
