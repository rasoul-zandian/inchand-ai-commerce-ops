"""Retrieval strategy selection for workflows (no vector DB, no OpenAI in default paths)."""

from __future__ import annotations

from enum import StrEnum

from app.rag.retriever import retrieve_documents
from app.rag.semantic_retriever import semantic_retrieve
from app.rag.types import RAGDocument, RAGResult
from app.rag.vector_store import VectorStore


class RetrievalStrategyName(StrEnum):
    MOCK = "mock"
    SEMANTIC = "semantic"
    POLICY_ONLY = "policy_only"
    APPROVED_EXAMPLES = "approved_examples"


def _coerce_strategy(strategy: RetrievalStrategyName | str) -> RetrievalStrategyName:
    if isinstance(strategy, RetrievalStrategyName):
        return strategy
    key = str(strategy).strip()
    try:
        return RetrievalStrategyName(key)
    except ValueError as exc:
        raise ValueError(f"Unsupported retrieval strategy: {strategy!r}") from exc


def retrieve_for_workflow(
    query: str,
    *,
    workflow_type: str,
    strategy: RetrievalStrategyName | str = RetrievalStrategyName.MOCK,
    top_k: int = 5,
    vector_store: VectorStore | None = None,
    embedding_provider: str = "mock",
    embedding_model: str = "mock-embedding-small",
) -> RAGResult:
    """Return RAG hits for a workflow using a named strategy (deterministic, no DB writes)."""
    name = _coerce_strategy(strategy)

    if name is RetrievalStrategyName.SEMANTIC:
        if vector_store is None:
            raise ValueError(
                "Semantic retrieval strategy requires an explicit VectorStore instance."
            )
        semantic_result = semantic_retrieve(
            query,
            store=vector_store,
            top_k=top_k,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        meta = dict(semantic_result.metadata)
        meta["strategy"] = "semantic"
        meta["workflow_type"] = workflow_type
        return RAGResult(
            documents=list(semantic_result.documents),
            provider=semantic_result.provider,
            metadata=meta,
        )

    if name is RetrievalStrategyName.MOCK:
        result = retrieve_documents(query, top_k=top_k, provider="mock")
        meta = dict(result.metadata)
        meta["strategy"] = "mock"
        meta["workflow_type"] = workflow_type
        return RAGResult(documents=list(result.documents), provider=result.provider, metadata=meta)

    base = retrieve_documents(query, top_k=top_k, provider="mock")

    if name is RetrievalStrategyName.POLICY_ONLY:
        filtered: list[RAGDocument] = [d for d in base.documents if d.source_type == "policy"]
        return RAGResult(
            documents=filtered,
            provider="strategy",
            metadata={
                "strategy": "policy_only",
                "workflow_type": workflow_type,
                "base_provider": base.provider,
                "result_count": len(filtered),
            },
        )

    if name is RetrievalStrategyName.APPROVED_EXAMPLES:
        filtered_ex: list[RAGDocument] = [
            d for d in base.documents if d.source_type == "approved_pattern"
        ]
        return RAGResult(
            documents=filtered_ex,
            provider="strategy",
            metadata={
                "strategy": "approved_examples",
                "workflow_type": workflow_type,
                "base_provider": base.provider,
                "result_count": len(filtered_ex),
            },
        )

    raise ValueError(f"Unsupported retrieval strategy: {strategy!r}")
