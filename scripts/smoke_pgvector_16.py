#!/usr/bin/env python3
"""Local smoke: mock 16-D corpus index + semantic search via PgVectorStore (no runtime wiring)."""

from __future__ import annotations

import os
import sys

from app.rag.bootstrap import default_vendor_ticket_documents
from app.rag.pgvector_store import PgVectorStore
from app.rag.semantic_retriever import semantic_retrieve
from app.rag.vector_records import rag_documents_to_vector_records

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_TABLE_NAME = "rag_vector_records_16"
_DIMENSIONS = 16
_EMBEDDING_PROVIDER = "mock"
_EMBEDDING_MODEL = "mock-embedding-small"
_SMOKE_QUERY = "تسویه من با فاکتور فروش هم‌خوان نیست"
_TOP_K = 3


def _database_url() -> str:
    return os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()


def run_smoke() -> int:
    documents = default_vendor_ticket_documents()
    records = rag_documents_to_vector_records(
        documents,
        embedding_provider=_EMBEDDING_PROVIDER,
        embedding_model=_EMBEDDING_MODEL,
    )

    for record in records:
        if record.dimensions != _DIMENSIONS or len(record.vector) != _DIMENSIONS:
            print("pgvector 16-D smoke: failed", file=sys.stderr)
            print(
                f"  unexpected vector dimensions ({record.dimensions}, "
                f"len={len(record.vector)}); expected {_DIMENSIONS}",
                file=sys.stderr,
            )
            return 1

    store = PgVectorStore(
        _database_url(),
        table_name=_TABLE_NAME,
        dimensions=_DIMENSIONS,
    )

    try:
        upserted_count = store.upsert(records)
    except Exception as exc:
        print("pgvector 16-D smoke: failed", file=sys.stderr)
        print(f"  upsert {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        result = semantic_retrieve(
            _SMOKE_QUERY,
            store=store,
            top_k=_TOP_K,
            embedding_provider=_EMBEDDING_PROVIDER,
            embedding_model=_EMBEDDING_MODEL,
        )
    except Exception as exc:
        print("pgvector 16-D smoke: failed", file=sys.stderr)
        print(f"  search {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    result_count = len(result.documents)
    print(f"document_count={len(documents)}")
    print(f"upserted_count={upserted_count}")
    print(f"result_count={result_count}")
    print(f"database_table={_TABLE_NAME}")
    print(f"pgvector_dimensions={_DIMENSIONS}")

    for index, doc in enumerate(result.documents, start=1):
        score = doc.score if doc.score is not None else 0.0
        print(
            f"top_{index} "
            f"document_id={doc.document_id} "
            f"title={doc.title!r} "
            f"source_type={doc.source_type} "
            f"score={score:.4f}"
        )

    if upserted_count > 0 and result_count > 0:
        print("pgvector 16-D smoke: passed")
        return 0

    print("pgvector 16-D smoke: failed", file=sys.stderr)
    if upserted_count <= 0:
        print("  upserted_count must be > 0", file=sys.stderr)
    if result_count <= 0:
        print("  result_count must be > 0", file=sys.stderr)
    return 1


def main() -> int:
    return run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
