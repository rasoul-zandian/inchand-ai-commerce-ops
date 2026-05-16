"""Tests for retrieval strategy layer and retrieve_context wiring (mock only, no OpenAI)."""

from __future__ import annotations

import uuid

import pytest
from app.nodes.common import retrieve_context
from app.rag.semantic_retriever import build_in_memory_store_from_documents
from app.rag.strategy import RetrievalStrategyName, retrieve_for_workflow
from app.rag.types import RAGDocument
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def test_mock_strategy_returns_rag_result_with_metadata() -> None:
    result = retrieve_for_workflow(
        "تسویه",
        workflow_type="vendor_ticket",
        strategy=RetrievalStrategyName.MOCK,
        top_k=5,
    )
    assert result.provider == "mock"
    assert len(result.documents) == 5
    assert result.metadata.get("strategy") == "mock"
    assert result.metadata.get("workflow_type") == "vendor_ticket"


def test_policy_only_filters_to_policy_documents() -> None:
    result = retrieve_for_workflow(
        "query",
        workflow_type="vendor_ticket",
        strategy=RetrievalStrategyName.POLICY_ONLY,
        top_k=5,
    )
    assert result.provider == "strategy"
    assert all(doc.source_type == "policy" for doc in result.documents)
    assert result.metadata["strategy"] == "policy_only"
    assert result.metadata["workflow_type"] == "vendor_ticket"
    assert result.metadata["base_provider"] == "mock"
    assert result.metadata["result_count"] == len(result.documents)
    assert len(result.documents) == 3


def test_approved_examples_filters_to_approved_pattern() -> None:
    result = retrieve_for_workflow(
        "query",
        workflow_type="vendor_ticket",
        strategy="approved_examples",
        top_k=5,
    )
    assert result.provider == "strategy"
    assert all(doc.source_type == "approved_pattern" for doc in result.documents)
    assert result.metadata["strategy"] == "approved_examples"
    assert result.metadata["result_count"] == len(result.documents)
    assert len(result.documents) == 1


def test_semantic_strategy_without_vector_store_raises_value_error() -> None:
    with pytest.raises(ValueError, match="explicit VectorStore"):
        retrieve_for_workflow(
            "q",
            workflow_type="vendor_ticket",
            strategy=RetrievalStrategyName.SEMANTIC,
            top_k=5,
        )


def test_semantic_strategy_with_explicit_store_returns_rag_result() -> None:
    docs = [
        RAGDocument(
            document_id="s1",
            title="الف",
            content="محتوای یکتا برای جستجو",
            source_type="policy",
            score=None,
            metadata={},
        ),
        RAGDocument(
            document_id="s2",
            title="ب",
            content="متن دیگر برای تمایز",
            source_type="policy",
            score=None,
            metadata={},
        ),
    ]
    store = build_in_memory_store_from_documents(docs)
    result = retrieve_for_workflow(
        "محتوای یکتا برای جستجو",
        workflow_type="vendor_ticket",
        strategy=RetrievalStrategyName.SEMANTIC,
        top_k=5,
        vector_store=store,
    )
    assert result.provider == "semantic"
    assert len(result.documents) >= 1
    assert result.documents[0].document_id == "s1"


def test_semantic_strategy_metadata_includes_strategy_workflow_and_retriever() -> None:
    doc = RAGDocument(
        document_id="meta-1",
        title="عنوان",
        content="ثابت-semantic-meta-test",
        source_type="approved_pattern",
        score=None,
        metadata={},
    )
    store = build_in_memory_store_from_documents([doc])
    result = retrieve_for_workflow(
        "ثابت-semantic-meta-test",
        workflow_type="custom_workflow",
        strategy="semantic",
        top_k=3,
        vector_store=store,
    )
    assert result.metadata.get("strategy") == "semantic"
    assert result.metadata.get("workflow_type") == "custom_workflow"
    assert result.metadata.get("retriever") == "semantic"


def test_semantic_strategy_top_k_limits_results() -> None:
    shared = "پایه-مشترک"
    documents = [
        RAGDocument(
            document_id=f"tk{i}",
            title=f"t{i}",
            content=f"{shared} شماره {i} جزئیات",
            source_type="policy",
            score=None,
            metadata={},
        )
        for i in range(4)
    ]
    store = build_in_memory_store_from_documents(documents)
    result = retrieve_for_workflow(
        f"{shared} شماره 2 جزئیات",
        workflow_type="vendor_ticket",
        strategy=RetrievalStrategyName.SEMANTIC,
        top_k=1,
        vector_store=store,
    )
    assert len(result.documents) == 1
    assert result.metadata.get("top_k") == 1


def test_unsupported_strategy_string_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported retrieval strategy"):
        retrieve_for_workflow(
            "q",
            workflow_type="vendor_ticket",
            strategy="weaviate",
            top_k=5,
        )


def test_retrieve_context_populates_rag_and_tool_results() -> None:
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
        "ticket_id": "t-rag-strategy-1",
        "application_id": None,
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
    }
    out = retrieve_context(state)
    assert len(out["rag_sources"]) == 5
    rag_docs = out["retrieved_context"].get("rag_documents") or []
    assert len(rag_docs) == 5

    rwf = out["tool_results"].get("retrieve_for_workflow") or {}
    assert rwf.get("ok") is True
    assert rwf.get("strategy") == "mock"
    assert rwf.get("count") == 5
    assert rwf.get("provider") == "mock"

    legacy = out["tool_results"].get("retrieve_documents") or {}
    assert legacy.get("ok") is True
    assert legacy.get("count") == 5
