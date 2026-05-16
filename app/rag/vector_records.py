"""Offline vector record preparation: RAGDocument + embedding → VectorRecord (no DB writes)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.embeddings import generate_embedding
from app.rag.types import RAGDocument


class VectorRecord(BaseModel):
    record_id: str
    document_id: str
    content: str
    vector: list[float]
    dimensions: int
    embedding_provider: str
    embedding_model: str
    source_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def rag_document_to_vector_record(
    document: RAGDocument,
    *,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> VectorRecord:
    """Attach an embedding vector to a single RAG document; pure in-memory transform."""
    embedding = generate_embedding(
        document.content,
        provider=embedding_provider,
        model=embedding_model,
    )
    metadata = dict(document.metadata)
    metadata["title"] = document.title
    metadata["embedding_metadata"] = dict(embedding.metadata)

    return VectorRecord(
        record_id=f"vec-{document.document_id}",
        document_id=document.document_id,
        content=document.content,
        vector=list(embedding.vector),
        dimensions=embedding.dimensions,
        embedding_provider=embedding.provider,
        embedding_model=embedding.model,
        source_type=document.source_type,
        metadata=metadata,
    )


def rag_documents_to_vector_records(
    documents: list[RAGDocument],
    *,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> list[VectorRecord]:
    """Batch-convert RAG documents to vector records; preserves input order."""
    if not documents:
        return []
    return [
        rag_document_to_vector_record(
            doc,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        for doc in documents
    ]
