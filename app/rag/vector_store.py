"""Provider-agnostic vector store interface with an in-memory implementation (no external DB)."""

from __future__ import annotations

from pydantic import BaseModel

from app.rag.types import RAGDocument
from app.rag.vector_records import VectorRecord


class VectorSearchResult(BaseModel):
    """Single hit from a vector similarity search."""

    record: VectorRecord
    score: float


class VectorStore:
    """Abstract vector index: upsert records and query by embedding vector."""

    def upsert(self, records: list[VectorRecord]) -> int:
        raise NotImplementedError

    def search(self, query_vector: list[float], *, top_k: int = 5) -> list[VectorSearchResult]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [−1, 1]; returns 0.0 for invalid inputs."""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na**0.5 * nb**0.5)


class InMemoryVectorStore(VectorStore):
    """Deterministic in-process store keyed by ``record_id``; cosine similarity for search.

    Dimension mismatch: records whose ``vector`` length differs from ``query_vector`` are
    **skipped** (not scored) so mixed-dimension batches do not raise.
    """

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> int:
        for rec in records:
            self._records[rec.record_id] = rec
        return len(records)

    def count(self) -> int:
        return len(self._records)

    def search(self, query_vector: list[float], *, top_k: int = 5) -> list[VectorSearchResult]:
        if not query_vector or top_k <= 0:
            return []
        if not self._records:
            return []

        qdim = len(query_vector)
        scored: list[tuple[float, VectorRecord]] = []
        for rec in self._records.values():
            if len(rec.vector) != qdim:
                continue
            score = cosine_similarity(query_vector, rec.vector)
            scored.append((score, rec))

        scored.sort(key=lambda item: item[0], reverse=True)
        trimmed = scored[:top_k]
        return [VectorSearchResult(record=rec, score=score) for score, rec in trimmed]


def vector_record_to_rag_document(
    record: VectorRecord,
    *,
    score: float | None = None,
) -> RAGDocument:
    """Map a stored vector row back to a RAGDocument for downstream RAG paths."""
    raw_title = record.metadata.get("title")
    title = str(raw_title) if raw_title not in (None, "") else record.document_id

    metadata = dict(record.metadata)
    metadata["vector_record_id"] = record.record_id
    metadata["embedding_provider"] = record.embedding_provider
    metadata["embedding_model"] = record.embedding_model
    metadata["dimensions"] = record.dimensions

    return RAGDocument(
        document_id=record.document_id,
        title=title,
        content=record.content,
        source_type=record.source_type,
        score=score,
        metadata=metadata,
    )
