"""Runtime RAG_STRATEGY wiring for retrieve_context (mock embeddings, no network)."""

from __future__ import annotations

import uuid

import pytest
from app.config import get_settings
from app.nodes.common import retrieve_context
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def _base_state() -> CommerceAIState:
    return {
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
        "ticket_id": "t-runtime-rag-1",
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


def test_default_config_uses_mock_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "mock")
    get_settings.cache_clear()
    assert get_settings().rag_strategy == "mock"
    out = retrieve_context(_base_state())
    assert out["errors"] == []
    assert len(out["rag_sources"]) == 5
    assert len(out["retrieved_context"].get("rag_documents") or []) == 5
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["strategy"] == "mock"
    assert rwf["provider"] == "mock"
    assert rwf["requested_strategy"] == "mock"
    assert rwf["effective_strategy"] == "mock"


def test_env_override_policy_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "policy_only")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    assert out["errors"] == []
    assert len(out["rag_sources"]) == 3
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["strategy"] == "policy_only"
    assert rwf["provider"] == "strategy"


def test_env_override_approved_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "approved_examples")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    assert out["errors"] == []
    assert len(out["rag_sources"]) == 1
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["strategy"] == "approved_examples"


def test_semantic_strategy_uses_bootstrap_and_mock_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "semantic")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_MODEL", "mock-embedding-small")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.embedding_provider == "mock"
    assert settings.embedding_model == "mock-embedding-small"
    out = retrieve_context(_base_state())
    assert out["errors"] == []
    assert out["rag_sources"]
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["strategy"] == "semantic"
    assert rwf["provider"] == "semantic"
    assert rwf["count"] == len(out["rag_sources"])


def test_invalid_strategy_falls_back_to_mock_and_records_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "weaviate")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    assert len(out["errors"]) == 1
    assert "Unsupported RAG strategy" in out["errors"][0].message
    assert "falling back to 'mock'" in out["errors"][0].message
    assert len(out["rag_sources"]) == 5
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["strategy"] == "mock"
    assert rwf["provider"] == "mock"
    assert rwf["requested_strategy"] == "weaviate"
    assert rwf["effective_strategy"] == "mock"


def test_rag_top_k_env_override_limits_retrieval_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "policy_only")
    monkeypatch.setenv("RAG_TOP_K", "2")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    assert out["errors"] == []
    assert len(out["rag_sources"]) == 2
    assert out["tool_results"]["retrieve_for_workflow"]["count"] == 2


def test_semantic_store_build_failure_falls_back_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "semantic")
    get_settings.cache_clear()

    def _boom(**_kwargs: object) -> object:
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr("app.nodes.common.build_default_vendor_ticket_vector_store", _boom)
    out = retrieve_context(_base_state())
    assert len(out["errors"]) == 1
    assert "Semantic RAG strategy failed" in out["errors"][0].message
    assert "falling back to 'mock'" in out["errors"][0].message
    assert len(out["rag_sources"]) == 5
    assert out["tool_results"]["retrieve_for_workflow"]["strategy"] == "mock"
