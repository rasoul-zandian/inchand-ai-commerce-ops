"""Sandbox knowledge retrieval tool (local pgvector; no runtime / draft activation)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.knowledge.knowledge_chunking import assert_chunk_safe
from app.knowledge.knowledge_embedding_index import rank_knowledge_search_results
from app.knowledge.knowledge_models import KnowledgeDocumentType, KnowledgeSourceLane
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import VectorSearchResult, VectorStore

QueryEmbeddingFn = Callable[[str], list[float]]

ALLOWED_KNOWLEDGE_NAMESPACE = "knowledge_operations_sandbox"
KNOWLEDGE_INDEX_VERSION_PREFIX = "knowledge_v"
MIN_TOP_K = 1
MAX_TOP_K = 10
MAX_SNIPPET_CHARS = 300

_FORBIDDEN_QUERY_MARKERS = (
    "user_input",
    "draft_response",
    "final_response",
    "gold_reference_reply",
    "snapshot_before_reply",
    '"messages"',
    "messages[",
    "conversation transcript",
)

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "conversation_transcript",
        "transcript",
        "raw_text",
        "draft_response",
        "final_response",
        "messages",
        "retrieved_context",
        "vector",
        "embedding",
        "embeddings",
        "openai_api_key",
    }
)


class KnowledgeRetrievalRequest(BaseModel):
    """Sandbox knowledge retrieval input."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=MIN_TOP_K, le=MAX_TOP_K)
    allowed_document_types: list[str] | None = None
    prefer_official_policy: bool = True

    @field_validator("allowed_document_types")
    @classmethod
    def normalize_allowed_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            try:
                KnowledgeDocumentType(text)
            except ValueError as exc:
                raise ValueError(f"invalid allowed_document_types entry: {text}") from exc
            normalized.append(text)
        return normalized or None


class KnowledgeRetrievalHit(BaseModel):
    """One safe knowledge hit (truncated snippet only)."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    source_lane: str
    document_type: str
    section_title: str
    score: float
    priority_rank: int
    snippet: str = Field(max_length=MAX_SNIPPET_CHARS)


class KnowledgeRetrievalResponse(BaseModel):
    """Sandbox knowledge retrieval output (governance-safe)."""

    model_config = ConfigDict(extra="forbid")

    hits: list[KnowledgeRetrievalHit]
    result_count: int
    official_policy_hit_count: int
    historical_memory_hit_count: int
    retrieval_activated: bool = False
    sandbox_only: bool = True


def validate_knowledge_namespace(namespace: str) -> str:
    text = namespace.strip()
    if text != ALLOWED_KNOWLEDGE_NAMESPACE:
        raise ValueError(
            f"namespace must be {ALLOWED_KNOWLEDGE_NAMESPACE!r} (got {text!r})",
        )
    return text


def validate_knowledge_index_version(index_version: str) -> str:
    text = index_version.strip()
    if not text.startswith(KNOWLEDGE_INDEX_VERSION_PREFIX):
        raise ValueError(
            f"index_version must start with {KNOWLEDGE_INDEX_VERSION_PREFIX!r}",
        )
    return text


def validate_knowledge_retrieval_request(
    request: KnowledgeRetrievalRequest | dict[str, Any],
) -> KnowledgeRetrievalRequest:
    """Parse and validate a knowledge retrieval request."""
    if isinstance(request, KnowledgeRetrievalRequest):
        model = request
    else:
        model = KnowledgeRetrievalRequest.model_validate(request)

    validate_knowledge_namespace(model.namespace)
    validate_knowledge_index_version(model.index_version)

    query = model.query.strip()
    if not query:
        raise ValueError("query must be non-empty")
    lowered = query.lower()
    for marker in _FORBIDDEN_QUERY_MARKERS:
        if marker in lowered:
            raise ValueError(f"query must not contain forbidden marker: {marker}")

    return model.model_copy(update={"query": query, "namespace": model.namespace.strip()})


def _truncate_snippet(text: str, *, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _record_matches_request(
    record: VectorRecord,
    *,
    namespace: str,
    index_version: str,
) -> bool:
    meta = record.metadata if isinstance(record.metadata, dict) else {}
    return (
        record.record_id.startswith("knowledge::")
        and str(meta.get("namespace")) == namespace
        and str(meta.get("index_version")) == index_version
    )


def _hit_from_search_result(hit: VectorSearchResult) -> KnowledgeRetrievalHit:
    meta = hit.record.metadata if isinstance(hit.record.metadata, dict) else {}
    raw_text = hit.record.content.strip()
    snippet = _truncate_snippet(raw_text)
    try:
        assert_chunk_safe(snippet)
    except ValueError as exc:
        raise ValueError(f"unsafe knowledge snippet: {exc}") from exc

    try:
        priority = int(meta.get("priority_rank", 0))
    except (TypeError, ValueError):
        priority = 0

    return KnowledgeRetrievalHit(
        chunk_id=str(meta.get("chunk_id", hit.record.document_id)),
        source_lane=str(meta.get("source_lane", "")),
        document_type=str(meta.get("document_type", "")),
        section_title=str(meta.get("section_title", "")),
        score=round(float(hit.score), 6),
        priority_rank=priority,
        snippet=snippet,
    )


def assert_safe_knowledge_retrieval_response(response: KnowledgeRetrievalResponse) -> None:
    """Fail closed if response may leak forbidden fields or activate retrieval."""
    if response.retrieval_activated is not False:
        raise ValueError("retrieval_activated must be false")
    if response.sandbox_only is not True:
        raise ValueError("sandbox_only must be true")
    if response.result_count != len(response.hits):
        raise ValueError("result_count must match len(hits)")

    serialized = response.model_dump_json().lower()
    for key in _FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in serialized:
            raise ValueError(f"response must not expose forbidden field: {key}")

    for hit in response.hits:
        if len(hit.snippet) > MAX_SNIPPET_CHARS:
            raise ValueError("snippet exceeds max length")
        if hit.source_lane not in {
            KnowledgeSourceLane.OFFICIAL_POLICY.value,
            KnowledgeSourceLane.HISTORICAL_MEMORY.value,
        }:
            raise ValueError(f"unexpected source_lane: {hit.source_lane}")


def execute_sandbox_knowledge_retrieval(
    request: KnowledgeRetrievalRequest | dict[str, Any],
    store: VectorStore,
    query_embedding_fn: QueryEmbeddingFn,
    *,
    candidate_multiplier: int = 8,
) -> KnowledgeRetrievalResponse:
    """Execute governed sandbox knowledge retrieval against a vector store."""
    validated = validate_knowledge_retrieval_request(request)
    ns = validate_knowledge_namespace(validated.namespace)
    version = validate_knowledge_index_version(validated.index_version)

    query_vector = query_embedding_fn(validated.query)
    if not query_vector:
        raise ValueError("query_embedding_fn returned an empty vector")

    fetch_k = max(validated.top_k * candidate_multiplier, validated.top_k)
    raw_hits = store.search(query_vector, top_k=fetch_k)

    filtered: list[VectorSearchResult] = []
    allowed = set(validated.allowed_document_types) if validated.allowed_document_types else None
    for hit in raw_hits:
        if not _record_matches_request(hit.record, namespace=ns, index_version=version):
            continue
        if allowed is not None:
            meta = hit.record.metadata or {}
            doc_type = str(meta.get("document_type", ""))
            if doc_type not in allowed:
                continue
        filtered.append(hit)

    if validated.prefer_official_policy:
        ranked = rank_knowledge_search_results(filtered)
    else:
        ranked = sorted(filtered, key=lambda item: item.score, reverse=True)

    hits = [_hit_from_search_result(item) for item in ranked[: validated.top_k]]
    official_count = sum(
        1 for h in hits if h.source_lane == KnowledgeSourceLane.OFFICIAL_POLICY.value
    )
    historical_count = sum(
        1 for h in hits if h.source_lane == KnowledgeSourceLane.HISTORICAL_MEMORY.value
    )

    response = KnowledgeRetrievalResponse(
        hits=hits,
        result_count=len(hits),
        official_policy_hit_count=official_count,
        historical_memory_hit_count=historical_count,
        retrieval_activated=False,
        sandbox_only=True,
    )
    assert_safe_knowledge_retrieval_response(response)
    return response


def knowledge_query_hash(query: str) -> str:
    """SHA-256 hex of query for audit logs without echoing query text."""
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()


def execute_sandbox_knowledge_retrieval_to_dict(
    request: KnowledgeRetrievalRequest | dict[str, Any],
    store: VectorStore,
    query_embedding_fn: QueryEmbeddingFn,
    *,
    candidate_multiplier: int = 8,
) -> dict[str, Any]:
    """Execute retrieval and return a JSON-serializable dict."""
    response = execute_sandbox_knowledge_retrieval(
        request,
        store,
        query_embedding_fn,
        candidate_multiplier=candidate_multiplier,
    )
    payload = response.model_dump()
    payload["query_hash"] = knowledge_query_hash(
        validate_knowledge_retrieval_request(request).query,
    )
    return payload
