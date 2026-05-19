"""PostgreSQL + pgvector ``VectorStore`` (sync psycopg; not wired to runtime retrieval yet)."""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.rag.vector_records import VectorRecord
from app.rag.vector_store import VectorSearchResult, VectorStore

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(table_name: str) -> str:
    """Allow only simple SQL identifiers (letters, digits, underscore)."""
    if not _TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(f"Invalid table name for PgVectorStore: {table_name!r}")
    return table_name


def _vector_literal(vector: list[float]) -> str:
    """Format a Python float list as a pgvector text literal (no user string interpolation)."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _validate_record_dimensions(record: VectorRecord, dimensions: int) -> None:
    if record.dimensions != dimensions:
        raise ValueError(
            f"VectorRecord dimensions {record.dimensions} != store dimensions {dimensions}"
        )
    if len(record.vector) != dimensions:
        raise ValueError(
            f"VectorRecord vector length {len(record.vector)} != store dimensions {dimensions}"
        )


def _parse_vector_column(value: Any) -> list[float]:
    if isinstance(value, list):
        return [float(x) for x in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [float(part) for part in inner.split(",")]
    raise TypeError("Unsupported vector column type from database")


class PgVectorStore(VectorStore):
    """Persist ``VectorRecord`` rows in PostgreSQL with the pgvector extension."""

    def __init__(
        self,
        database_url: str,
        *,
        table_name: str = "rag_vector_records",
        dimensions: int = 1536,
    ) -> None:
        self._database_url = database_url
        self._table_name = _validate_table_name(table_name)
        self._dimensions = dimensions

    def upsert(self, records: list[VectorRecord]) -> int:
        if not records:
            return 0

        for record in records:
            _validate_record_dimensions(record, self._dimensions)

        table = self._table_name
        sql = f"""
            INSERT INTO {table} (
                record_id,
                document_id,
                source_type,
                content,
                embedding_provider,
                embedding_model,
                dimensions,
                vector,
                metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::vector, %s
            )
            ON CONFLICT (record_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                source_type = EXCLUDED.source_type,
                content = EXCLUDED.content,
                embedding_provider = EXCLUDED.embedding_provider,
                embedding_model = EXCLUDED.embedding_model,
                dimensions = EXCLUDED.dimensions,
                vector = EXCLUDED.vector,
                metadata = EXCLUDED.metadata,
                updated_at = now()
        """

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                for record in records:
                    cur.execute(
                        sql,
                        (
                            record.record_id,
                            record.document_id,
                            record.source_type,
                            record.content,
                            record.embedding_provider,
                            record.embedding_model,
                            record.dimensions,
                            _vector_literal(record.vector),
                            Jsonb(record.metadata),
                        ),
                    )
            conn.commit()

        return len(records)

    def search(self, query_vector: list[float], *, top_k: int = 5) -> list[VectorSearchResult]:
        if not query_vector or top_k <= 0:
            return []
        if len(query_vector) != self._dimensions:
            return []

        table = self._table_name
        query_literal = _vector_literal(query_vector)
        sql = f"""
            SELECT
                record_id,
                document_id,
                source_type,
                content,
                embedding_provider,
                embedding_model,
                dimensions,
                metadata,
                vector::text AS vector_text,
                (vector <=> %s::vector) AS distance
            FROM {table}
            ORDER BY vector <=> %s::vector
            LIMIT %s
        """

        results: list[VectorSearchResult] = []
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (query_literal, query_literal, top_k))
                rows = cur.fetchall()

        for row in rows:
            distance = float(row[9])
            score = 1.0 - distance
            metadata = row[7]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            elif not isinstance(metadata, dict):
                metadata = dict(metadata) if metadata is not None else {}

            record = VectorRecord(
                record_id=row[0],
                document_id=row[1],
                source_type=row[2],
                content=row[3],
                embedding_provider=row[4],
                embedding_model=row[5],
                dimensions=int(row[6]),
                vector=_parse_vector_column(row[8]),
                metadata=metadata,
            )
            results.append(VectorSearchResult(record=record, score=score))

        return results

    def fetch_by_record_id_prefix(self, prefix: str) -> list[VectorRecord]:
        """Load rows whose ``record_id`` starts with ``prefix`` (no vector ranking)."""
        needle = prefix.strip()
        if not needle:
            return []

        table = self._table_name
        sql = f"""
            SELECT
                record_id,
                document_id,
                source_type,
                content,
                embedding_provider,
                embedding_model,
                dimensions,
                metadata,
                vector::text AS vector_text
            FROM {table}
            WHERE record_id LIKE %s
            ORDER BY record_id
        """
        pattern = f"{needle}%"
        records: list[VectorRecord] = []
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (pattern,))
                rows = cur.fetchall()

        for row in rows:
            metadata = row[7]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            elif not isinstance(metadata, dict):
                metadata = dict(metadata) if metadata is not None else {}

            records.append(
                VectorRecord(
                    record_id=row[0],
                    document_id=row[1],
                    source_type=row[2],
                    content=row[3],
                    embedding_provider=row[4],
                    embedding_model=row[5],
                    dimensions=int(row[6]),
                    vector=_parse_vector_column(row[8]),
                    metadata=metadata,
                )
            )

        return records

    def count(self) -> int:
        table = self._table_name
        sql = f"SELECT COUNT(*) FROM {table}"
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])
