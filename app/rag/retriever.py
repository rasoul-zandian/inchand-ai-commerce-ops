"""Provider-agnostic document retrieval entry point."""

from __future__ import annotations

from app.rag.mock_retriever import mock_retrieve
from app.rag.types import RAGQuery, RAGResult


def retrieve_documents(query: str, *, top_k: int = 5, provider: str = "mock") -> RAGResult:
    """Retrieve supporting documents; ``mock`` uses the in-process catalog."""
    normalized = provider.strip().lower()
    if normalized == "mock":
        return mock_retrieve(RAGQuery(query=query, top_k=top_k))
    raise ValueError(f"Unsupported RAG provider: {provider!r}")
