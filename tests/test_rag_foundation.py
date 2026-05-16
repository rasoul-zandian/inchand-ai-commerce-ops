"""RAG foundation: types, mock retriever, and retrieve_context wiring (no external calls)."""

from __future__ import annotations

import uuid

import pytest
from app.nodes.common import retrieve_context
from app.rag import RAGQuery, RAGResult, retrieve_documents
from app.rag.mock_retriever import mock_retrieve
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def test_mock_retrieve_returns_rag_result() -> None:
    result = mock_retrieve(RAGQuery(query="تسویه فروشنده", top_k=5))
    assert isinstance(result, RAGResult)
    assert result.provider == "mock"
    assert len(result.documents) == 5
    assert result.documents[0].title


def test_mock_retrieve_top_k_limits_documents() -> None:
    result = mock_retrieve(RAGQuery(query="x", top_k=2))
    assert len(result.documents) == 2


def test_mock_retrieve_top_k_zero_returns_empty() -> None:
    result = mock_retrieve(RAGQuery(query="x", top_k=0))
    assert result.documents == []


def test_retrieve_documents_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported RAG provider"):
        retrieve_documents("q", top_k=3, provider="pinecone")


def test_retrieve_context_populates_rag_sources_and_documents() -> None:
    state: CommerceAIState = {
        "request_id": str(uuid.uuid4()),
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "user_input": "سلام، تسویه مشکل دارد",
        "workflow_type": WorkflowType.VENDOR_TICKET,
        "workflow_status": WorkflowStatus.IN_PROGRESS,
        "entity_type": EntityType.TICKET,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": "t-rag-1",
        "application_id": None,
        "room_id": None,
        "ticket_label": None,
        "ticket_subtype": None,
        "workflow_state_snapshot": {},
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "detected_intent": None,
        "grounding_summary": None,
        "grounding_sources": [],
        "qa_passed": None,
        "qa_issues": [],
        "qa_warnings": [],
        "qa_summary": None,
        "qa_requires_human_attention": False,
        "route_label": None,
        "routing_reasons": [],
        "specialist_recommended_action": None,
        "review_category": None,
        "review_priority": None,
        "review_reason": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
    }
    out = retrieve_context(state)
    assert out["rag_sources"]
    assert len(out["rag_sources"]) == 5
    assert out["rag_sources"][0].chunk_id
    rag_docs = out["retrieved_context"].get("rag_documents") or []
    assert len(rag_docs) == 5
    assert rag_docs[0].get("document_id")
    assert out["tool_results"].get("retrieve_documents", {}).get("ok") is True
    assert out["tool_results"].get("retrieve_documents", {}).get("count") == 5
