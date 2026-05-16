"""Vector record preparation (mock embeddings only; no OpenAI in tests)."""

from __future__ import annotations

from copy import deepcopy

from app.rag.types import RAGDocument
from app.rag.vector_records import (
    VectorRecord,
    rag_document_to_vector_record,
    rag_documents_to_vector_records,
)


def test_single_document_to_vector_record() -> None:
    doc = RAGDocument(
        document_id="ticket-1-chunk-0",
        title="عنوان",
        content="hello world",
        source_type="vendor_ticket",
        score=None,
        metadata={"region": "eu"},
    )
    rec = rag_document_to_vector_record(doc)
    assert isinstance(rec, VectorRecord)
    assert rec.record_id == "vec-ticket-1-chunk-0"
    assert rec.document_id == "ticket-1-chunk-0"
    assert rec.content == "hello world"
    assert rec.dimensions == 16
    assert len(rec.vector) == 16
    assert rec.embedding_provider == "mock"
    assert rec.embedding_model == "mock-embedding-small"
    assert rec.source_type == "vendor_ticket"
    assert rec.metadata.get("region") == "eu"
    assert rec.metadata.get("title") == "عنوان"
    assert isinstance(rec.metadata.get("embedding_metadata"), dict)
    assert rec.metadata["embedding_metadata"].get("digest")


def test_document_metadata_not_mutated() -> None:
    original = {"k": 1}
    snapshot = deepcopy(original)
    doc = RAGDocument(
        document_id="d",
        title="t",
        content="body",
        source_type="s",
        metadata=original,
    )
    rag_document_to_vector_record(doc)
    assert doc.metadata == snapshot


def test_mock_embedding_deterministic_vector() -> None:
    doc = RAGDocument(
        document_id="x",
        title="t",
        content="same",
        source_type="vendor_ticket",
        metadata={},
    )
    a = rag_document_to_vector_record(doc)
    b = rag_document_to_vector_record(doc)
    assert a.vector == b.vector


def test_batch_preserves_order_and_empty() -> None:
    docs = [
        RAGDocument(document_id=f"id-{i}", title="t", content=str(i), source_type="s", metadata={})
        for i in range(3)
    ]
    recs = rag_documents_to_vector_records(docs)
    assert [r.document_id for r in recs] == ["id-0", "id-1", "id-2"]
    assert rag_documents_to_vector_records([]) == []
