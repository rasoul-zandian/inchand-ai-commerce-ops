"""Embedding factory tests (mock only; no OpenAI network)."""

from __future__ import annotations

import pytest
from app.embeddings import EmbeddingResponse, generate_embedding


def test_mock_embedding_returns_embedding_response() -> None:
    out = generate_embedding("hello", provider="mock", model="mock-embedding-small")
    assert isinstance(out, EmbeddingResponse)
    assert out.provider == "mock"
    assert out.model == "mock-embedding-small"
    assert out.dimensions == 16
    assert len(out.vector) == 16
    assert out.metadata.get("text_length") == 5
    assert out.metadata.get("digest")


def test_mock_embedding_is_deterministic() -> None:
    a = generate_embedding("same", provider="mock", model="mock-embedding-small")
    b = generate_embedding("same", provider="mock", model="mock-embedding-small")
    assert a.vector == b.vector
    assert a.metadata.get("digest") == b.metadata.get("digest")


def test_mock_embedding_dimensions_are_sixteen() -> None:
    out = generate_embedding("x", provider="mock", model="m")
    assert out.dimensions == 16


def test_unsupported_embedding_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        generate_embedding("t", provider="weaviate", model="m")


def test_openai_embedding_without_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(
        RuntimeError,
        match="OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai",
    ):
        generate_embedding("no-key", provider="openai", model="text-embedding-3-small")
