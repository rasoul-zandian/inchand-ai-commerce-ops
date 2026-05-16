"""Typed retrieval configuration for workflow RAG (decoupled from AppSettings)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator

from app.rag.strategy import RetrievalStrategyName


class RetrievalProfileName(StrEnum):
    """Named retrieval presets for runtime workflow context loading."""

    MOCK = "mock"
    POLICY_ONLY = "policy_only"
    APPROVED_EXAMPLES = "approved_examples"
    SEMANTIC_LOCAL = "semantic_local"
    SEMANTIC_PGVECTOR_16 = "semantic_pgvector_16"
    SEMANTIC_PGVECTOR = "semantic_pgvector"
    CUSTOM = "custom"


class RetrievalConfig(BaseModel):
    """Validated retrieval parameters for ``retrieve_context`` and related paths."""

    strategy: str = "mock"
    embedding_provider: str = "mock"
    embedding_model: str = "mock-embedding-small"
    top_k: int = 5
    profile: str | None = None
    vector_store_provider: str | None = None

    @field_validator("strategy", "embedding_provider", "embedding_model", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("profile", mode="before")
    @classmethod
    def _strip_profile(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    @field_validator("vector_store_provider", mode="before")
    @classmethod
    def _strip_vector_store_provider(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    @field_validator("top_k")
    @classmethod
    def _top_k_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("top_k must be >= 1")
        return value

    def normalized_strategy(self) -> str:
        return self.strategy.strip().lower()

    def normalized_vector_store_provider(self) -> str | None:
        if self.vector_store_provider is None:
            return None
        return self.vector_store_provider.strip().lower()

    def to_strategy_name(self) -> RetrievalStrategyName | None:
        try:
            return RetrievalStrategyName(self.normalized_strategy())
        except ValueError:
            return None


def _coerce_profile(profile: RetrievalProfileName | str) -> RetrievalProfileName:
    key = str(profile).strip().lower()
    try:
        return RetrievalProfileName(key)
    except ValueError as exc:
        raise ValueError(f"Unsupported retrieval profile: {profile!r}") from exc


def retrieval_config_from_profile(
    profile: RetrievalProfileName | str,
    *,
    fallback_strategy: str = "mock",
    fallback_top_k: int = 5,
    fallback_embedding_provider: str = "mock",
    fallback_embedding_model: str = "mock-embedding-small",
) -> RetrievalConfig:
    """Resolve a named retrieval profile to a ``RetrievalConfig``."""
    name = _coerce_profile(profile)
    if name is RetrievalProfileName.CUSTOM:
        return RetrievalConfig(
            strategy=fallback_strategy,
            embedding_provider=fallback_embedding_provider,
            embedding_model=fallback_embedding_model,
            top_k=fallback_top_k,
        )
    if name is RetrievalProfileName.MOCK:
        return RetrievalConfig(
            strategy="mock",
            top_k=5,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
        )
    if name is RetrievalProfileName.POLICY_ONLY:
        return RetrievalConfig(
            strategy="policy_only",
            top_k=5,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
        )
    if name is RetrievalProfileName.APPROVED_EXAMPLES:
        return RetrievalConfig(
            strategy="approved_examples",
            top_k=5,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
        )
    if name is RetrievalProfileName.SEMANTIC_LOCAL:
        return RetrievalConfig(
            strategy="semantic",
            top_k=5,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
        )
    if name is RetrievalProfileName.SEMANTIC_PGVECTOR_16:
        return RetrievalConfig(
            strategy="semantic",
            top_k=5,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
            vector_store_provider="pgvector",
        )
    if name is RetrievalProfileName.SEMANTIC_PGVECTOR:
        return RetrievalConfig(
            strategy="semantic",
            top_k=5,
            embedding_provider=fallback_embedding_provider,
            embedding_model=fallback_embedding_model,
            vector_store_provider="pgvector",
        )
    raise ValueError(f"Unsupported retrieval profile: {profile!r}")


def build_retrieval_config_from_settings(settings: Any) -> RetrievalConfig:
    """Build ``RetrievalConfig`` from ``AppSettings`` (or any object with the same fields)."""
    fallback_strategy = settings.rag_strategy
    fallback_top_k = getattr(settings, "rag_top_k", 5)
    fallback_embedding_provider = settings.embedding_provider
    fallback_embedding_model = settings.embedding_model

    raw_profile = getattr(settings, "rag_profile", None)
    profile_str = (raw_profile or "").strip() if raw_profile is not None else ""
    if profile_str:
        cfg = retrieval_config_from_profile(
            profile_str,
            fallback_strategy=fallback_strategy,
            fallback_top_k=fallback_top_k,
            fallback_embedding_provider=fallback_embedding_provider,
            fallback_embedding_model=fallback_embedding_model,
        )
        return cfg.model_copy(update={"profile": profile_str})

    return RetrievalConfig(
        strategy=fallback_strategy,
        embedding_provider=fallback_embedding_provider,
        embedding_model=fallback_embedding_model,
        top_k=fallback_top_k,
        profile=None,
    )
