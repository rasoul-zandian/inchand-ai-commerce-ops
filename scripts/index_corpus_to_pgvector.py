#!/usr/bin/env python3
"""Offline index: vendor-ticket corpus → VectorRecord → PgVectorStore (no runtime wiring)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from app.rag.bootstrap import default_vendor_ticket_documents
from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_records import VectorRecord, rag_documents_to_vector_records

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_CORPUS_NAME = "vendor_ticket"


@dataclass(frozen=True)
class IndexConfig:
    database_url: str
    table_name: str
    dimensions: int
    embedding_provider: str
    embedding_model: str
    dry_run: bool
    corpus_name: str = _CORPUS_NAME


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_index_config_from_env() -> IndexConfig:
    return IndexConfig(
        database_url=os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip(),
        table_name=os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip(),
        dimensions=int(os.environ.get("PGVECTOR_DIMENSIONS", "1536")),
        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "mock").strip(),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "mock-embedding-small").strip(),
        dry_run=_env_bool("DRY_RUN"),
    )


_DIMENSION_MISMATCH_HINT = (
    "Mock embeddings are 16-D; the default migration uses VECTOR(1536). "
    "Use an embedding model that produces the configured dimension, or align "
    "PGVECTOR_DIMENSIONS with your table schema (e.g. 16 for mock-only test tables)."
)


def validate_vector_dimensions(
    records: list[VectorRecord],
    *,
    expected_dimensions: int,
) -> str | None:
    """Return an error message when any record does not match ``expected_dimensions``."""
    for record in records:
        if record.dimensions != expected_dimensions or len(record.vector) != expected_dimensions:
            return (
                f"Vector dimensions ({record.dimensions}, len={len(record.vector)}) "
                f"do not match PGVECTOR_DIMENSIONS ({expected_dimensions}). "
                f"{_DIMENSION_MISMATCH_HINT}"
            )
    return None


def _print_summary(
    *,
    config: IndexConfig,
    document_count: int,
    vector_record_count: int,
    upserted_count: int,
    record_dimensions: int,
) -> None:
    print(f"corpus_name={config.corpus_name}")
    print(f"document_count={document_count}")
    print(f"vector_record_count={vector_record_count}")
    if config.dry_run:
        print(f"would_upsert_count={upserted_count}")
    else:
        print(f"upserted_count={upserted_count}")
    print(f"embedding_provider={config.embedding_provider}")
    print(f"embedding_model={config.embedding_model}")
    print(f"database_table={config.table_name}")
    print(f"pgvector_dimensions={config.dimensions}")
    print(f"record_dimensions={record_dimensions}")


def run_index(config: IndexConfig | None = None) -> int:
    cfg = config or load_index_config_from_env()

    documents = default_vendor_ticket_documents()
    records = rag_documents_to_vector_records(
        documents,
        embedding_provider=cfg.embedding_provider,
        embedding_model=cfg.embedding_model,
    )

    dim_error = validate_vector_dimensions(records, expected_dimensions=cfg.dimensions)
    if dim_error:
        print("corpus index: failed", file=sys.stderr)
        print(f"  {dim_error}", file=sys.stderr)
        return 1

    record_dimensions = records[0].dimensions if records else cfg.dimensions

    if cfg.dry_run:
        _print_summary(
            config=cfg,
            document_count=len(documents),
            vector_record_count=len(records),
            upserted_count=len(records),
            record_dimensions=record_dimensions,
        )
        print("corpus index dry-run: passed")
        return 0

    store = PgVectorStore(
        cfg.database_url,
        table_name=cfg.table_name,
        dimensions=cfg.dimensions,
    )
    try:
        upserted = store.upsert(records)
    except Exception as exc:
        print("corpus index: failed", file=sys.stderr)
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_summary(
        config=cfg,
        document_count=len(documents),
        vector_record_count=len(records),
        upserted_count=upserted,
        record_dimensions=record_dimensions,
    )
    print("corpus index: success")
    return 0


def main() -> int:
    return run_index()


if __name__ == "__main__":
    raise SystemExit(main())
