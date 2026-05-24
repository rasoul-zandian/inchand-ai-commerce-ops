"""Sandbox pgvector indexing for operational knowledge chunks (no production RAG)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.corpus_planning.embedding_dry_run import build_mock_embedding
from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.embeddings import generate_embedding
from app.knowledge.knowledge_chunking import (
    CONFLICT_RESOLUTION,
    KnowledgeChunk,
    assert_chunk_safe,
)
from app.knowledge.knowledge_models import (
    KnowledgeDocumentType,
    KnowledgeSourceLane,
    KnowledgeVisibility,
)
from app.rag.pgvector_store import PgVectorStore
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import VectorSearchResult

KNOWLEDGE_SOURCE_TYPE = "knowledge_operations"
_OPENAI_MODEL_DEFAULT = "text-embedding-3-small"
_OPENAI_DIMENSIONS_DEFAULT = 1536

_FORBIDDEN_OUTPUT_TOKENS = (
    "openai_api_key",
    "sk-",
    "begin private key",
    "conversation_transcript",
)

_RECORD_ID_RE = re.compile(r"^knowledge::[a-z_]+::[a-z_]+::.+$")


@dataclass(frozen=True)
class LoadedKnowledgeChunk:
    """One chunk row from ``knowledge_chunks_preview.jsonl``."""

    chunk: KnowledgeChunk

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LoadedKnowledgeChunk:
        try:
            source_lane = KnowledgeSourceLane(str(payload["source_lane"]))
            document_type = KnowledgeDocumentType(str(payload["document_type"]))
            visibility = KnowledgeVisibility(str(payload["visibility"]))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid knowledge chunk payload: {exc}") from exc
        chunk = KnowledgeChunk(
            chunk_id=str(payload["chunk_id"]),
            source_lane=source_lane,
            document_type=document_type,
            doc_id=str(payload["doc_id"]),
            title=str(payload["title"]),
            section_title=str(payload["section_title"]),
            text=str(payload["text"]),
            visibility=visibility,
            owner=str(payload["owner"]),
            language=str(payload["language"]),
            version=str(payload["version"]),
            priority_rank=int(payload["priority_rank"]),
            char_count=int(payload.get("char_count", len(str(payload["text"])))),
        )
        return cls(chunk=chunk)


@dataclass(frozen=True)
class KnowledgeEmbeddingBatch:
    """Chunks with aligned embedding vectors."""

    chunks: tuple[LoadedKnowledgeChunk, ...]
    vectors: tuple[list[float], ...]
    provider: str
    model: str
    dimensions: int


@dataclass(frozen=True)
class KnowledgeIndexingResult:
    indexed_count: int
    namespace: str
    index_version: str
    provider: str
    model: str
    dimensions: int
    skipped_unsafe: int
    summary_path: Path | None = None


def load_knowledge_chunks(jsonl_path: Path) -> list[LoadedKnowledgeChunk]:
    """Load validated chunk rows from Step 163 preview JSONL."""
    if not jsonl_path.is_file():
        raise FileNotFoundError(f"knowledge chunks file not found: {jsonl_path}")

    loaded: list[LoadedKnowledgeChunk] = []
    for line_no, line in enumerate(
        jsonl_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {jsonl_path}:{line_no}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        item = LoadedKnowledgeChunk.from_dict(payload)
        assert_chunk_safe(item.chunk.text)
        loaded.append(item)
    return loaded


def generate_knowledge_embeddings(
    chunks: list[LoadedKnowledgeChunk],
    *,
    provider: str,
    model: str,
    dimensions: int = _OPENAI_DIMENSIONS_DEFAULT,
    confirm_real_openai: bool = False,
) -> KnowledgeEmbeddingBatch:
    """Embed chunk text (mock deterministic or OpenAI)."""
    normalized = provider.strip().lower()
    if normalized not in {"mock", "openai"}:
        raise ValueError(f"unsupported embedding provider: {provider!r}")

    if normalized == "openai":
        if not confirm_real_openai:
            raise ValueError("provider=openai requires confirm_real_openai=True")
        if model.strip() != _OPENAI_MODEL_DEFAULT:
            raise ValueError(f"openai knowledge indexing expects model {_OPENAI_MODEL_DEFAULT!r}")
        vectors: list[list[float]] = []
        for item in chunks:
            emb = generate_embedding(item.chunk.text, provider="openai", model=model)
            if len(emb.vector) != dimensions:
                raise ValueError(
                    f"embedding dimensions {len(emb.vector)} != expected {dimensions}",
                )
            vectors.append(list(emb.vector))
        return KnowledgeEmbeddingBatch(
            chunks=tuple(chunks),
            vectors=tuple(vectors),
            provider="openai",
            model=model,
            dimensions=dimensions,
        )

    vectors = [build_mock_embedding(item.chunk.text, dimensions) for item in chunks]
    return KnowledgeEmbeddingBatch(
        chunks=tuple(chunks),
        vectors=tuple(vectors),
        provider="mock",
        model=model,
        dimensions=dimensions,
    )


def build_knowledge_record_id(chunk: KnowledgeChunk) -> str:
    """``knowledge::{source_lane}::{document_type}::{chunk_id}``."""
    return f"knowledge::{chunk.source_lane.value}::{chunk.document_type.value}::{chunk.chunk_id}"


def validate_knowledge_record_id(record_id: str) -> None:
    if not _RECORD_ID_RE.match(record_id):
        raise ValueError(f"invalid knowledge record_id format: {record_id!r}")


def build_knowledge_vector_records(
    batch: KnowledgeEmbeddingBatch,
    *,
    namespace: str,
    index_version: str,
) -> list[VectorRecord]:
    """Build ``VectorRecord`` rows with lane metadata (sandbox knowledge only)."""
    ns = namespace.strip()
    version = index_version.strip()
    if not ns or not version:
        raise ValueError("namespace and index_version must be non-empty")

    records: list[VectorRecord] = []
    for item, vector in zip(batch.chunks, batch.vectors, strict=True):
        chunk = item.chunk
        record_id = build_knowledge_record_id(chunk)
        validate_knowledge_record_id(record_id)

        metadata = {
            "source_lane": chunk.source_lane.value,
            "document_type": chunk.document_type.value,
            "doc_id": chunk.doc_id,
            "title": chunk.title,
            "section_title": chunk.section_title,
            "visibility": chunk.visibility.value,
            "owner": chunk.owner,
            "language": chunk.language,
            "version": chunk.version,
            "priority_rank": chunk.priority_rank,
            "conflict_resolution": CONFLICT_RESOLUTION,
            "namespace": ns,
            "index_version": version,
            "chunk_id": chunk.chunk_id,
            "knowledge_sandbox": True,
            "sandbox_only": True,
            "retrieval_activated": False,
        }
        serialized = json.dumps({"content": chunk.text, "metadata": metadata}, ensure_ascii=False)
        lowered = serialized.lower()
        for token in ("user_input", "draft_response", "final_response", '"messages"'):
            if token in lowered:
                raise ValueError(f"chunk {chunk.chunk_id!r}: forbidden content marker {token}")

        records.append(
            VectorRecord(
                record_id=record_id,
                document_id=chunk.doc_id,
                content=chunk.text,
                vector=[float(v) for v in vector],
                dimensions=batch.dimensions,
                embedding_provider=batch.provider,
                embedding_model=batch.model,
                source_type=KNOWLEDGE_SOURCE_TYPE,
                metadata=metadata,
            ),
        )
    return records


def index_knowledge_chunks_pgvector(
    records: list[VectorRecord],
    *,
    database_url: str,
    table_name: str = "rag_vector_records",
    dimensions: int = _OPENAI_DIMENSIONS_DEFAULT,
    upsert_fn: Callable[[list[VectorRecord]], int] | None = None,
) -> int:
    """Upsert knowledge vector records into local sandbox pgvector."""
    assert_sandbox_database_url(database_url)
    if not records:
        return 0
    for record in records:
        if record.dimensions != dimensions or len(record.vector) != dimensions:
            raise ValueError(
                f"record {record.record_id}: dimensions mismatch (expected {dimensions})",
            )
    if upsert_fn is not None:
        return upsert_fn(records)
    store = PgVectorStore(database_url, table_name=table_name, dimensions=dimensions)
    return store.upsert(records)


def summarize_knowledge_indexing(
    *,
    indexed_count: int,
    namespace: str,
    index_version: str,
    provider: str,
    model: str,
    dimensions: int,
    chunk_count: int,
    skipped_unsafe: int,
    chunks_by_source_lane: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "indexed_count": indexed_count,
        "chunk_count": chunk_count,
        "skipped_unsafe": skipped_unsafe,
        "namespace": namespace,
        "index_version": index_version,
        "embedding_provider": provider,
        "embedding_model": model,
        "dimensions": dimensions,
        "conflict_resolution": CONFLICT_RESOLUTION,
        "official_policy_priority_rank": 10,
        "historical_memory_priority_rank": 1,
        "chunks_by_source_lane": dict(sorted((chunks_by_source_lane or {}).items())),
        "indexing_status": "sandbox_indexed",
        "retrieval_activated": False,
        "record_id_prefix": "knowledge::",
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def assert_safe_knowledge_output(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token in lowered:
            raise RuntimeError(f"unsafe output token detected: {token}")


def _record_matches_namespace(record: VectorRecord, *, namespace: str, index_version: str) -> bool:
    meta = record.metadata or {}
    return (
        str(meta.get("namespace")) == namespace
        and str(meta.get("index_version")) == index_version
        and record.record_id.startswith("knowledge::")
    )


def rank_knowledge_search_results(
    results: list[VectorSearchResult],
) -> list[VectorSearchResult]:
    """Sort by ``priority_rank`` (official first), then similarity score."""

    def sort_key(item: VectorSearchResult) -> tuple[int, float]:
        rank = item.record.metadata.get("priority_rank", 0)
        try:
            priority = int(rank)
        except (TypeError, ValueError):
            priority = 0
        return (priority, item.score)

    return sorted(results, key=sort_key, reverse=True)


def query_knowledge_pgvector(
    query_text: str,
    *,
    namespace: str,
    index_version: str,
    database_url: str,
    table_name: str = "rag_vector_records",
    dimensions: int = _OPENAI_DIMENSIONS_DEFAULT,
    top_k: int = 5,
    provider: str = "mock",
    model: str = _OPENAI_MODEL_DEFAULT,
    confirm_real_openai: bool = False,
    search_fn: Callable[[list[float], int], list[VectorSearchResult]] | None = None,
    candidate_multiplier: int = 8,
) -> list[dict[str, Any]]:
    """Sandbox semantic search with lane-aware ranking (safe summary fields only)."""
    assert_sandbox_database_url(database_url)
    if not query_text.strip():
        raise ValueError("query must be non-empty")

    if provider.strip().lower() == "openai":
        if not confirm_real_openai:
            raise ValueError("provider=openai requires confirm_real_openai=True")
        query_vector = list(
            generate_embedding(query_text, provider="openai", model=model).vector,
        )
    else:
        query_vector = build_mock_embedding(query_text, dimensions)

    if len(query_vector) != dimensions:
        raise ValueError(f"query embedding length {len(query_vector)} != {dimensions}")

    if search_fn is not None:
        raw = search_fn(query_vector, max(top_k * candidate_multiplier, top_k))
    else:
        store = PgVectorStore(database_url, table_name=table_name, dimensions=dimensions)
        raw = store.search(query_vector, top_k=max(top_k * candidate_multiplier, top_k))

    filtered = [
        hit
        for hit in raw
        if _record_matches_namespace(hit.record, namespace=namespace, index_version=index_version)
    ]
    ranked = rank_knowledge_search_results(filtered)[:top_k]

    summaries: list[dict[str, Any]] = []
    for hit in ranked:
        meta = hit.record.metadata
        text = hit.record.content.strip()
        snippet = text if len(text) <= 300 else text[:299].rstrip() + "…"
        summaries.append(
            {
                "chunk_id": meta.get("chunk_id", hit.record.document_id),
                "source_lane": meta.get("source_lane"),
                "document_type": meta.get("document_type"),
                "section_title": meta.get("section_title"),
                "score": round(hit.score, 6),
                "priority_rank": meta.get("priority_rank"),
                "text_snippet": snippet,
            },
        )
    return summaries
