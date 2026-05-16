"""Semantic RAG retrieval: query embedding, vector search, RAGResult (no vector DB)."""

from __future__ import annotations

from typing import Any

from app.embeddings import generate_embedding
from app.rag.types import RAGDocument, RAGResult
from app.rag.vector_records import rag_documents_to_vector_records
from app.rag.vector_store import InMemoryVectorStore, VectorStore, vector_record_to_rag_document


def _semantic_metadata(
    *,
    embedding_provider: str,
    embedding_model: str,
    top_k: int,
    result_count: int,
    query_embedding_dimensions: int,
) -> dict[str, Any]:
    return {
        "retriever": "semantic",
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "top_k": top_k,
        "result_count": result_count,
        "query_embedding_dimensions": query_embedding_dimensions,
    }


def semantic_retrieve(
    query: str,
    *,
    store: VectorStore,
    top_k: int = 5,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> RAGResult:
    """Embed ``query``, search ``store``, map hits to ``RAGDocument`` rows with similarity scores.

    Side effects are limited to ``generate_embedding`` and ``store.search`` (no DB writes).

    Empty or whitespace-only ``query`` yields no embedding call and no store search; metadata
    still records the configured embedding settings with ``result_count`` 0 and dimensions 0.
    """
    text = query.strip() if query else ""
    if not text:
        return RAGResult(
            documents=[],
            provider="semantic",
            metadata=_semantic_metadata(
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                top_k=top_k,
                result_count=0,
                query_embedding_dimensions=0,
            ),
        )

    query_embedding = generate_embedding(
        text,
        provider=embedding_provider,
        model=embedding_model,
    )
    hits = store.search(query_embedding.vector, top_k=top_k)
    documents = [
        vector_record_to_rag_document(result.record, score=result.score) for result in hits
    ]
    return RAGResult(
        documents=documents,
        provider="semantic",
        metadata=_semantic_metadata(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            top_k=top_k,
            result_count=len(documents),
            query_embedding_dimensions=query_embedding.dimensions,
        ),
    )


def build_in_memory_store_from_documents(
    documents: list[RAGDocument],
    *,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> InMemoryVectorStore:
    """Build an ``InMemoryVectorStore`` from ``RAGDocument`` rows using mock-compatible embeddings.

    Document order is preserved when generating ``VectorRecord`` rows and when upserting.
    """
    store = InMemoryVectorStore()
    records = rag_documents_to_vector_records(
        documents,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    if records:
        store.upsert(records)
    return store
