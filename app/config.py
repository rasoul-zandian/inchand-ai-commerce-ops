"""Application settings loaded from environment variables and optional `.env` file."""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.config import RetrievalProfileName


class AppSettings(BaseSettings):
    """Runtime configuration; secrets must not be committed (use `.env` locally, never in git)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Inchand AI Commerce Operations Copilot"
    environment: str = "development"
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "inchand-ai-commerce-mvp"
    llm_provider: str = "mock"
    llm_model: str = "mock-vendor-ticket-drafter"
    openai_api_key: str | None = None
    embedding_provider: str = "mock"
    embedding_model: str = "mock-embedding-small"
    rag_strategy: str = Field(
        default="mock",
        description=(
            "RAG retrieval strategy for workflow context loading. "
            "Valid values: mock (default catalog), semantic (local in-memory bootstrap store), "
            "policy_only, approved_examples. Unknown values fall back to mock at runtime."
        ),
    )
    rag_top_k: int = Field(
        default=5,
        ge=1,
        description="Maximum RAG documents requested during workflow retrieval.",
    )
    rag_profile: str | None = Field(
        default=None,
        description=(
            "Optional retrieval profile preset (mock, policy_only, approved_examples, "
            "semantic_local, semantic_pgvector_16, semantic_pgvector, custom). "
            "When set, controls "
            "strategy/top_k/embedding fields; "
            "custom uses rag_strategy/rag_top_k/embedding_* overrides."
        ),
    )
    vector_store_provider: str = Field(
        default="memory",
        description=(
            "Vector store backend: memory (default) or pgvector "
            "(used when RAG_PROFILE is a pgvector preset)."
        ),
    )
    pgvector_database_url: str | None = Field(
        default=None,
        description="Postgres URL for PgVectorStore when vector_store_provider=pgvector.",
        repr=False,
    )
    pgvector_table: str = Field(
        default="rag_vector_records",
        description="Table name for PgVectorStore when vector_store_provider=pgvector.",
    )
    pgvector_dimensions: int = Field(
        default=1536,
        ge=1,
        description="Embedding dimensions for PgVectorStore (must match table VECTOR width).",
    )
    review_action_adapter: str = Field(
        default="noop",
        description=(
            "Operator review action persistence adapter: noop (default, no storage) "
            "or memory (in-process test/dev only)."
        ),
    )

    @field_validator("review_action_adapter", mode="before")
    @classmethod
    def _normalize_review_action_adapter(cls, value: Any) -> str:
        if value is None:
            return "noop"
        if not isinstance(value, str):
            return value
        return value.strip().lower() or "noop"

    @field_validator("pgvector_database_url", mode="before")
    @classmethod
    def _empty_pgvector_url_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("rag_profile", mode="before")
    @classmethod
    def normalize_and_validate_rag_profile(cls, value: Any) -> str | None:
        """Normalize empty profile to None; validate known presets at settings load."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not normalized:
            return None
        try:
            RetrievalProfileName(normalized)
        except ValueError as exc:
            allowed = ", ".join(profile.value for profile in RetrievalProfileName)
            raise ValueError(f"Invalid RAG_PROFILE {value!r}; allowed values: {allowed}") from exc
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings.

    Call ``get_settings.cache_clear()`` in tests when overriding environment.
    """
    return AppSettings()
