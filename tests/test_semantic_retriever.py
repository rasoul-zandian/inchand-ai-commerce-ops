"""Tests for semantic RAG retrieval (mock embeddings, in-memory vector store only)."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from app.rag.semantic_retriever import (
    build_in_memory_store_from_documents,
    semantic_retrieve,
)
from app.rag.types import RAGDocument, RAGResult


def _doc(document_id: str, content: str, *, title: str | None = None) -> RAGDocument:
    meta: dict = {}
    if title is not None:
        meta["title"] = title
    return RAGDocument(
        document_id=document_id,
        title=title or document_id,
        content=content,
        source_type="vendor_ticket",
        metadata=meta,
    )


def test_semantic_retrieve_returns_rag_result() -> None:
    store = build_in_memory_store_from_documents([_doc("d1", "hello world")])
    out = semantic_retrieve("hello world", store=store)
    assert isinstance(out, RAGResult)
    assert out.provider == "semantic"
    assert isinstance(out.documents, list)
    assert out.metadata.get("retriever") == "semantic"


def test_semantic_retrieve_empty_query_returns_empty_documents() -> None:
    store = build_in_memory_store_from_documents([_doc("d1", "x")])
    for q in ("", "   ", "\t\n"):
        out = semantic_retrieve(q, store=store)
        assert out.documents == []
        assert out.provider == "semantic"
        assert out.metadata["result_count"] == 0
        assert out.metadata["query_embedding_dimensions"] == 0


def test_semantic_retrieve_result_count_metadata() -> None:
    docs = [_doc(f"id{i}", f"body-{i}-unique") for i in range(4)]
    store = build_in_memory_store_from_documents(docs)
    out = semantic_retrieve("body-2-unique", store=store, top_k=5)
    assert out.metadata["result_count"] == len(out.documents)
    assert out.metadata["result_count"] >= 1


def test_semantic_retrieve_documents_have_scores() -> None:
    store = build_in_memory_store_from_documents(
        [_doc("a", "alpha"), _doc("b", "beta-long-string")]
    )
    out = semantic_retrieve("alpha", store=store, top_k=5)
    assert out.documents
    for doc in out.documents:
        assert doc.score is not None
        assert isinstance(doc.score, float)


def test_semantic_retrieve_top_k_limits_results() -> None:
    docs = [_doc(f"id{i}", f"chunk-{i}-payload") for i in range(5)]
    store = build_in_memory_store_from_documents(docs)
    out = semantic_retrieve("chunk-2-payload", store=store, top_k=2)
    assert len(out.documents) <= 2
    assert out.metadata["result_count"] == len(out.documents)
    assert out.metadata["top_k"] == 2


def test_build_in_memory_store_count_matches_documents() -> None:
    docs = [_doc(f"id{i}", f"c{i}") for i in range(3)]
    store = build_in_memory_store_from_documents(docs)
    assert store.count() == len(docs)


def test_build_in_memory_store_empty_documents() -> None:
    store = build_in_memory_store_from_documents([])
    assert store.count() == 0


def test_build_does_not_mutate_original_document_metadata() -> None:
    nested = {"k": 1}
    doc = RAGDocument(
        document_id="d-mut",
        title="T",
        content="stable-content-for-mock",
        source_type="vendor_ticket",
        metadata={"nested": nested, "keep": True},
    )
    before = deepcopy(doc.metadata)
    build_in_memory_store_from_documents([doc])
    assert doc.metadata == before
    assert doc.metadata["nested"] is nested


def test_semantic_retrieve_empty_query_does_not_call_openai_embedding() -> None:
    store = build_in_memory_store_from_documents([_doc("d1", "x")])
    with patch("app.rag.semantic_retriever.generate_embedding") as gen:
        out = semantic_retrieve("  ", store=store, embedding_provider="openai")
        gen.assert_not_called()
    assert out.documents == []
