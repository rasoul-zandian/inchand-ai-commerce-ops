"""Sandbox-only retrieval tool executor (local pgvector; no LangGraph activation)."""

from __future__ import annotations

from collections.abc import Callable

from app.corpus_planning.pilot_retrieval_eval import (
    PilotMetadataFilter,
    PilotScopedVectorStore,
    assert_eval_profile,
)
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolRequest,
    RetrievalToolResponse,
    RetrievalToolResult,
    query_hash,
    retrieval_tool_response_to_dict,
)
from app.corpus_planning.retrieval_tool_validation import (
    assert_safe_retrieval_tool_response,
    validate_retrieval_tool_request,
)
from app.rag.vector_store import VectorSearchResult, VectorStore

QueryEmbeddingFn = Callable[[str], list[float]]


def _tool_filter_to_pilot_filter(
    metadata_filter: RetrievalToolMetadataFilter | None,
) -> PilotMetadataFilter | None:
    if metadata_filter is None:
        return None
    return PilotMetadataFilter(
        ticket_label=metadata_filter.ticket_label,
        route_label=metadata_filter.route_label,
        review_priority=metadata_filter.review_priority,
    )


def _active_pilot_metadata_filter(request: RetrievalToolRequest) -> PilotMetadataFilter | None:
    if request.eval_mode == "vector_only":
        return None
    return _tool_filter_to_pilot_filter(request.metadata_filter)


def _ensure_scoped_store(
    store: VectorStore,
    *,
    namespace: str,
    index_version: str,
) -> PilotScopedVectorStore:
    if not isinstance(store, PilotScopedVectorStore):
        raise ValueError("sandbox retrieval requires PilotScopedVectorStore")
    if store._namespace != namespace.strip() or store._index_version != index_version.strip():
        raise ValueError("PilotScopedVectorStore namespace/index_version must match the request")
    return store


def _result_from_search_hit(hit: VectorSearchResult) -> RetrievalToolResult:
    metadata = hit.record.metadata if isinstance(hit.record.metadata, dict) else {}
    return RetrievalToolResult(
        record_id=hit.record.record_id,
        score=float(hit.score),
        ticket_label=str(metadata.get("ticket_label", "")).strip(),
        route_label=str(metadata.get("route_label", "")).strip(),
        review_priority=str(metadata.get("review_priority", "")).strip(),
    )


def execute_sandbox_retrieval_tool(
    request: RetrievalToolRequest | dict,
    store: VectorStore,
    query_embedding_fn: QueryEmbeddingFn,
    *,
    profile: str = "semantic_pgvector",
) -> RetrievalToolResponse:
    """Execute a governed sandbox retrieval request against a scoped pilot index."""
    validated = validate_retrieval_tool_request(request)
    assert_eval_profile(profile)

    scoped = _ensure_scoped_store(
        store,
        namespace=validated.namespace,
        index_version=validated.index_version,
    )

    query_vector = query_embedding_fn(validated.query.strip())
    if not query_vector:
        raise ValueError("query_embedding_fn returned an empty vector")

    pilot_filter = _active_pilot_metadata_filter(validated)
    hits = scoped.search(
        query_vector,
        top_k=validated.top_k,
        metadata_filter=pilot_filter,
    )

    results = [_result_from_search_hit(hit) for hit in hits]
    response = RetrievalToolResponse(
        results=results,
        retrieval_activated=False,
        sandbox_only=True,
        query_hash=query_hash(validated.query),
        result_count=len(results),
    )
    assert_safe_retrieval_tool_response(response)
    return response


def execute_sandbox_retrieval_tool_to_dict(
    request: RetrievalToolRequest | dict,
    store: VectorStore,
    query_embedding_fn: QueryEmbeddingFn,
    *,
    profile: str = "semantic_pgvector",
) -> dict:
    """Execute sandbox retrieval and return a safe JSON-serializable dict."""
    response = execute_sandbox_retrieval_tool(
        request,
        store,
        query_embedding_fn,
        profile=profile,
    )
    return retrieval_tool_response_to_dict(response)
