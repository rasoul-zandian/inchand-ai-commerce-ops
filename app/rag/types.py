"""RAG request/response types (no vector store coupling)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RAGDocument(BaseModel):
    document_id: str
    title: str
    content: str
    source_type: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGQuery(BaseModel):
    query: str
    top_k: int = 5
    filters: dict[str, Any] = Field(default_factory=dict)


class RAGResult(BaseModel):
    documents: list[RAGDocument]
    provider: str
    metadata: dict[str, Any] = Field(default_factory=dict)
