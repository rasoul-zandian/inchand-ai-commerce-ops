"""Tests for default vendor-ticket RAG bootstrap (mock embeddings, in-memory only)."""

from __future__ import annotations

from app.rag.bootstrap import (
    build_default_vendor_ticket_vector_store,
    default_vendor_ticket_documents,
    retrieve_semantic_vendor_ticket_context,
)
from app.rag.types import RAGResult


def test_default_vendor_ticket_documents_non_empty() -> None:
    docs = default_vendor_ticket_documents()
    assert len(docs) >= 5
    types = {d.source_type for d in docs}
    assert "policy" in types
    assert "approved_pattern" in types
    assert "style_guide" in types


def test_default_documents_have_vendor_ticket_workflow_metadata() -> None:
    for doc in default_vendor_ticket_documents():
        assert doc.metadata.get("workflow_type") == "vendor_ticket"
        assert doc.metadata.get("locale") == "fa-IR"
        assert doc.metadata.get("domain")


def test_build_default_vendor_ticket_vector_store_count_matches_docs() -> None:
    docs = default_vendor_ticket_documents()
    store = build_default_vendor_ticket_vector_store()
    assert store.count() == len(docs)


def test_retrieve_semantic_vendor_ticket_context_returns_rag_result() -> None:
    out = retrieve_semantic_vendor_ticket_context("تسویه و فاکتور هم‌خوان نیست")
    assert isinstance(out, RAGResult)
    assert out.provider == "semantic"
    assert out.metadata.get("strategy") == "semantic"
    assert out.metadata.get("workflow_type") == "vendor_ticket"


def test_retrieve_semantic_top_k_limits_results() -> None:
    out = retrieve_semantic_vendor_ticket_context("پشتیبانی فروشنده", top_k=2)
    assert len(out.documents) <= 2


def test_retrieve_semantic_documents_have_scores() -> None:
    out = retrieve_semantic_vendor_ticket_context("تسویه مالی و بازپرداخت")
    assert out.documents
    for doc in out.documents:
        assert doc.score is not None
        assert isinstance(doc.score, float)


def test_retrieve_semantic_deterministic_document_order() -> None:
    query = "ابهام تسویه و صورتحساب فروشنده"
    first = retrieve_semantic_vendor_ticket_context(query, top_k=4)
    second = retrieve_semantic_vendor_ticket_context(query, top_k=4)
    assert [d.document_id for d in first.documents] == [d.document_id for d in second.documents]
