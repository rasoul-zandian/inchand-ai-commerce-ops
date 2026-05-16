"""Tests for offline corpus indexing script (no live Postgres in default CI)."""

from __future__ import annotations

import os

import pytest
from app.rag.types import RAGDocument
from app.rag.vector_records import VectorRecord
from scripts.index_corpus_to_pgvector import (
    IndexConfig,
    load_index_config_from_env,
    run_index,
    validate_vector_dimensions,
)


def test_load_index_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGVECTOR_DATABASE_URL", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    cfg = load_index_config_from_env()
    assert cfg.table_name == "rag_vector_records"
    assert cfg.dimensions == 1536
    assert cfg.embedding_provider == "mock"
    assert cfg.dry_run is False


def test_validate_vector_dimensions_mismatch_message() -> None:
    records = [
        VectorRecord(
            record_id="vec-a",
            document_id="doc-a",
            content="x",
            vector=[0.0] * 16,
            dimensions=16,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
            source_type="policy",
        )
    ]
    err = validate_vector_dimensions(records, expected_dimensions=1536)
    assert err is not None
    assert "16" in err
    assert "1536" in err


def test_dry_run_mock_embeddings_fail_against_1536_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = IndexConfig(
        database_url="postgresql://user:secret@127.0.0.1:5432/db",
        table_name="rag_vector_records",
        dimensions=1536,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        dry_run=True,
    )
    assert run_index(cfg) == 1
    captured = capsys.readouterr()
    assert "corpus index: failed" in captured.err
    assert "secret" not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err


def test_dry_run_matching_dimensions_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_doc = RAGDocument(
        document_id="doc-test",
        title="t",
        content="body",
        source_type="policy",
    )
    fake_record = VectorRecord(
        record_id="vec-doc-test",
        document_id="doc-test",
        content="body",
        vector=[0.1] * 16,
        dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        source_type="policy",
    )

    monkeypatch.setattr(
        "scripts.index_corpus_to_pgvector.default_vendor_ticket_documents",
        lambda: [fake_doc],
    )
    monkeypatch.setattr(
        "scripts.index_corpus_to_pgvector.rag_documents_to_vector_records",
        lambda *_args, **_kwargs: [fake_record],
    )

    cfg = IndexConfig(
        database_url="postgresql://inchand:inchand@127.0.0.1:5432/inchand_ai",
        table_name="rag_vector_records",
        dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        dry_run=True,
    )
    assert run_index(cfg) == 0
    out = capsys.readouterr().out
    assert "corpus index dry-run: passed" in out
    assert "would_upsert_count=1" in out
    assert "record_dimensions=16" in out
    assert "inchand_dev_password" not in out


def test_dry_run_skips_pgvector_store_on_dimension_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _should_not_construct(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("PgVectorStore should not be constructed")

    monkeypatch.setattr("scripts.index_corpus_to_pgvector.PgVectorStore", _should_not_construct)
    cfg = IndexConfig(
        database_url="postgresql://inchand:inchand@127.0.0.1:5432/inchand_ai",
        table_name="rag_vector_records",
        dimensions=1536,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        dry_run=False,
    )
    assert run_index(cfg) == 1


@pytest.mark.pgvector
def test_index_upsert_live_1536_vectors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL not set")

    dims = 1536
    fake_doc = RAGDocument(
        document_id="pgvector-index-int",
        title="integration",
        content="integration body",
        source_type="policy",
    )
    fake_record = VectorRecord(
        record_id="vec-pgvector-index-int",
        document_id="pgvector-index-int",
        content="integration body",
        vector=[0.01] * dims,
        dimensions=dims,
        embedding_provider="test",
        embedding_model="synthetic-1536",
        source_type="policy",
    )
    monkeypatch.setattr(
        "scripts.index_corpus_to_pgvector.default_vendor_ticket_documents",
        lambda: [fake_doc],
    )
    monkeypatch.setattr(
        "scripts.index_corpus_to_pgvector.rag_documents_to_vector_records",
        lambda *_args, **_kwargs: [fake_record],
    )

    cfg = IndexConfig(
        database_url=url,
        table_name=os.environ.get("PGVECTOR_TABLE", "rag_vector_records"),
        dimensions=dims,
        embedding_provider="test",
        embedding_model="synthetic-1536",
        dry_run=False,
    )
    assert run_index(cfg) == 0
    out = capsys.readouterr().out
    assert "upserted_count=1" in out
    assert url not in out
