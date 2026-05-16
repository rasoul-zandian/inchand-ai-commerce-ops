"""Tests for vector store interface and cosine similarity (in-memory only)."""

from __future__ import annotations

from copy import deepcopy

import pytest
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import (
    InMemoryVectorStore,
    cosine_similarity,
    vector_record_to_rag_document,
)


def test_cosine_similarity_identical_vectors() -> None:
    v = [0.1, 0.2, 0.3]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_dimension_mismatch() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_similarity_empty_or_zero_norm() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_in_memory_store_upsert_and_count() -> None:
    store = InMemoryVectorStore()
    rec = VectorRecord(
        record_id="vec-1",
        document_id="d1",
        content="c",
        vector=[1.0, 0.0, 0.0],
        dimensions=3,
        embedding_provider="mock",
        embedding_model="m",
        source_type="vendor_ticket",
        metadata={},
    )
    assert store.upsert([rec]) == 1
    assert store.count() == 1


def test_in_memory_store_upsert_replaces() -> None:
    store = InMemoryVectorStore()
    first = VectorRecord(
        record_id="vec-same",
        document_id="d",
        content="old",
        vector=[1.0, 0.0],
        dimensions=2,
        embedding_provider="mock",
        embedding_model="m",
        source_type="vendor_ticket",
        metadata={},
    )
    second = VectorRecord(
        record_id="vec-same",
        document_id="d",
        content="new",
        vector=[0.0, 1.0],
        dimensions=2,
        embedding_provider="mock",
        embedding_model="m",
        source_type="vendor_ticket",
        metadata={},
    )
    store.upsert([first])
    store.upsert([second])
    assert store.count() == 1
    assert store._records["vec-same"].content == "new"


def test_search_top_k_sorted_desc() -> None:
    store = InMemoryVectorStore()
    records = [
        VectorRecord(
            record_id=f"vec-{i}",
            document_id=f"d-{i}",
            content=str(i),
            vector=vec,
            dimensions=3,
            embedding_provider="mock",
            embedding_model="m",
            source_type="vendor_ticket",
            metadata={},
        )
        for i, vec in enumerate([[1.0, 0.0, 0.0], [0.7, 0.7, 0.0], [0.0, 0.0, 1.0]])
    ]
    store.upsert(records)
    query = [1.0, 0.0, 0.0]
    hits = store.search(query, top_k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert hits[0].record.record_id == "vec-0"


def test_search_empty_store_and_empty_query() -> None:
    store = InMemoryVectorStore()
    assert store.search([1.0, 0.0]) == []
    store.upsert(
        [
            VectorRecord(
                record_id="vec-1",
                document_id="d",
                content="c",
                vector=[1.0, 0.0],
                dimensions=2,
                embedding_provider="mock",
                embedding_model="m",
                source_type="vendor_ticket",
                metadata={},
            )
        ]
    )
    assert store.search([], top_k=5) == []
    assert store.search([1.0, 0.0, 0.0], top_k=5) == []  # dimension mismatch → skip all


def test_vector_record_to_rag_document_roundtrip_metadata() -> None:
    record = VectorRecord(
        record_id="vec-abc",
        document_id="doc-1",
        content="body text",
        source_type="vendor_ticket",
        vector=[0.1] * 16,
        dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        metadata={"title": "تیتر", "region": "eu"},
    )
    snap = deepcopy(record.metadata)
    doc = vector_record_to_rag_document(record, score=0.9)
    assert doc.content == "body text"
    assert doc.title == "تیتر"
    assert doc.score == 0.9
    assert doc.metadata.get("vector_record_id") == "vec-abc"
    assert doc.metadata.get("embedding_provider") == "mock"
    assert doc.metadata.get("dimensions") == 16
    assert record.metadata == snap


def test_vector_record_to_rag_document_title_fallback() -> None:
    record = VectorRecord(
        record_id="vec-x",
        document_id="fallback-id",
        content="c",
        vector=[0.0] * 16,
        dimensions=16,
        embedding_provider="mock",
        embedding_model="m",
        source_type="vendor_ticket",
        metadata={},
    )
    doc = vector_record_to_rag_document(record)
    assert doc.title == "fallback-id"
