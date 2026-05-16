"""Unit and optional integration tests for PgVectorStore (no live Postgres in default CI)."""

from __future__ import annotations

import os
import uuid

import pytest
from app.rag.pgvector_store import (
    PgVectorStore,
    _validate_record_dimensions,
    _validate_table_name,
    _vector_literal,
)
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import VectorSearchResult


def test_validate_table_name_accepts_safe_names() -> None:
    assert _validate_table_name("rag_vector_records") == "rag_vector_records"
    assert _validate_table_name("vectors_2024") == "vectors_2024"


@pytest.mark.parametrize(
    "name",
    [
        "rag;drop",
        "rag-vector",
        "rag.vector",
        "rag vector",
        "",
        "1starts_with_digit",
    ],
)
def test_validate_table_name_rejects_dangerous_names(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid table name"):
        _validate_table_name(name)


def test_vector_literal_format() -> None:
    assert _vector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


def test_validate_record_dimensions_mismatch_raises() -> None:
    record = VectorRecord(
        record_id="vec-x",
        document_id="doc-x",
        content="body",
        vector=[0.1, 0.2],
        dimensions=1536,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        source_type="policy",
    )
    with pytest.raises(ValueError, match="vector length"):
        _validate_record_dimensions(record, 1536)


def test_search_empty_query_returns_empty_without_db() -> None:
    store = PgVectorStore("postgresql://inchand:inchand@127.0.0.1:5432/inchand_ai")
    assert store.search([], top_k=5) == []


def test_search_wrong_dimension_returns_empty_without_db() -> None:
    store = PgVectorStore("postgresql://inchand:inchand@127.0.0.1:5432/inchand_ai", dimensions=3)
    assert store.search([0.1, 0.2], top_k=5) == []


def test_upsert_dimension_mismatch_raises_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PgVectorStore("postgresql://inchand:inchand@127.0.0.1:5432/inchand_ai", dimensions=3)

    def _should_not_connect(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("psycopg.connect should not be called")

    monkeypatch.setattr("app.rag.pgvector_store.psycopg.connect", _should_not_connect)
    bad = VectorRecord(
        record_id="vec-bad",
        document_id="doc-bad",
        content="x",
        vector=[0.1, 0.2],
        dimensions=3,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        source_type="policy",
    )
    with pytest.raises(ValueError, match="vector length"):
        store.upsert([bad])


def _pgvector_database_url() -> str | None:
    return os.environ.get("PGVECTOR_TEST_DATABASE_URL")


def _vector_1536(*, first: float = 0.0, second: float = 0.0) -> list[float]:
    """Minimal 1536-d vectors for integration tests (matches migration VECTOR(1536))."""
    v = [0.0] * 1536
    v[0] = first
    if second:
        v[1] = second
    return v


def _make_record(
    *,
    record_id: str,
    vector: list[float],
    document_id: str | None = None,
) -> VectorRecord:
    return VectorRecord(
        record_id=record_id,
        document_id=document_id or record_id,
        content=f"content for {record_id}",
        vector=vector,
        dimensions=len(vector),
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        source_type="policy",
        metadata={"title": record_id},
    )


@pytest.mark.pgvector
def test_pgvector_store_count_upsert_search_idempotent() -> None:
    url = _pgvector_database_url()
    if not url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL not set")

    store = PgVectorStore(url, dimensions=1536)
    prefix = f"test-pgv-{uuid.uuid4().hex[:8]}"
    ids = [f"{prefix}-a", f"{prefix}-b"]

    try:
        assert store.count() >= 0

        r1 = _make_record(record_id=ids[0], vector=_vector_1536(first=1.0))
        r2 = _make_record(record_id=ids[1], vector=_vector_1536(second=1.0))
        assert store.upsert([r1, r2]) == 2

        r1_updated = _make_record(record_id=ids[0], vector=_vector_1536(first=0.9, second=0.1))
        r1_updated = r1_updated.model_copy(update={"content": "updated content"})
        assert store.upsert([r1_updated]) == 1

        hits = store.search(_vector_1536(first=1.0), top_k=2)
        assert hits
        assert all(isinstance(h, VectorSearchResult) for h in hits)
        assert hits[0].record.record_id == ids[0]
        assert hits[0].score <= 1.0
    finally:
        with __import__("psycopg").connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_vector_records WHERE record_id = ANY(%s)",
                    (ids,),
                )
            conn.commit()
