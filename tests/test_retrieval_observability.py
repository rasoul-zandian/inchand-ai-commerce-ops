"""Retrieval config observability in audit_log, tool_results, and API responses."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.api.main import _serialize_state, app
from app.config import get_settings
from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.common import retrieve_context
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState
from fastapi.testclient import TestClient

_SECRET_SUBSTRINGS = ("api_key", "secret", "password", "token", "authorization")


def _assert_no_secrets(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = str(key).lower()
            assert not any(part in key_lower for part in _SECRET_SUBSTRINGS)
            _assert_no_secrets(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_secrets(item)
    elif isinstance(payload, str):
        value_lower = payload.lower()
        assert "sk-" not in value_lower


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
        "ticket_id": "t-obs-1",
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


def _retrieve_context_audit(out: CommerceAIState) -> dict[str, Any]:
    entry = next(e for e in out["audit_log"] if e.node_name == "retrieve_context")
    return dict(entry.metadata)


def test_default_mock_retrieval_summary_in_api_response() -> None:
    state = run_vendor_ticket_demo(user_input="test observability")
    response = _serialize_state(state)
    summary = response.retrieval_summary
    assert summary["requested_strategy"] == "mock"
    assert summary["effective_strategy"] == "mock"
    assert summary["provider"] == "mock"
    assert summary["count"] == 5
    assert summary["top_k"] == 5
    assert summary["embedding_provider"] == "mock"
    assert summary["embedding_model"] == "mock-embedding-small"
    assert summary.get("rag_profile") is None
    _assert_no_secrets(summary)


def test_api_run_vendor_ticket_includes_retrieval_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "mock")
    get_settings.cache_clear()
    client = TestClient(app)
    res = client.post("/run-vendor-ticket", json={"user_input": "سلام"})
    assert res.status_code == 200
    body = res.json()
    assert "retrieval_summary" in body
    assert body["retrieval_summary"]["effective_strategy"] == "mock"
    _assert_no_secrets(body["retrieval_summary"])


def test_semantic_retrieval_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "semantic")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_MODEL", "mock-embedding-small")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["requested_strategy"] == "semantic"
    assert rwf["effective_strategy"] == "semantic"
    assert rwf["strategy"] == "semantic"
    audit = _retrieve_context_audit(out)
    assert audit["requested_rag_strategy"] == "semantic"
    assert audit["effective_rag_strategy"] == "semantic"
    assert audit["rag_document_count"] == len(out["rag_sources"])
    response = _serialize_state(out)
    assert response.retrieval_summary["requested_strategy"] == "semantic"
    assert response.retrieval_summary["effective_strategy"] == "semantic"


def test_invalid_strategy_fallback_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "weaviate")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    assert len(out["errors"]) == 1
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["requested_strategy"] == "weaviate"
    assert rwf["effective_strategy"] == "mock"
    assert rwf["strategy"] == "mock"
    audit = _retrieve_context_audit(out)
    assert audit["requested_rag_strategy"] == "weaviate"
    assert audit["effective_rag_strategy"] == "mock"
    response = _serialize_state(out)
    assert response.retrieval_summary["requested_strategy"] == "weaviate"
    assert response.retrieval_summary["effective_strategy"] == "mock"


def test_audit_log_includes_retrieval_config_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRATEGY", "policy_only")
    monkeypatch.setenv("RAG_TOP_K", "3")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    audit = _retrieve_context_audit(out)
    assert audit["requested_rag_strategy"] == "policy_only"
    assert audit["effective_rag_strategy"] == "policy_only"
    assert audit["rag_provider"] == "strategy"
    assert audit["rag_top_k"] == 3
    assert audit["embedding_provider"] == "mock"
    assert audit["embedding_model"] == "mock-embedding-small"
    assert audit["rag_document_count"] == len(out["rag_sources"])
    assert audit["rag_document_count"] <= 3
    _assert_no_secrets(audit)


def test_mock_profile_retrieval_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "mock")
    monkeypatch.setenv("RAG_STRATEGY", "semantic")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["rag_profile"] == "mock"
    assert rwf["requested_strategy"] == "mock"
    assert rwf["effective_strategy"] == "mock"
    response = _serialize_state(out)
    assert response.retrieval_summary["rag_profile"] == "mock"
    assert response.retrieval_summary["effective_strategy"] == "mock"


def test_semantic_local_profile_retrieval_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_local")
    get_settings.cache_clear()
    out = retrieve_context(_base_state())
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["rag_profile"] == "semantic_local"
    assert rwf["requested_strategy"] == "semantic"
    assert rwf["effective_strategy"] == "semantic"
    audit = _retrieve_context_audit(out)
    assert audit["rag_profile"] == "semantic_local"
    response = _serialize_state(out)
    assert response.retrieval_summary["rag_profile"] == "semantic_local"
    assert response.retrieval_summary["effective_strategy"] == "semantic"


def test_retrieval_summary_empty_when_tool_results_missing() -> None:
    state = _base_state()
    response = _serialize_state(state)
    assert response.retrieval_summary == {}


def test_semantic_pgvector_16_profile_uses_create_vector_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_pgvector_16")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pgvector")
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setenv("PGVECTOR_TABLE", "rag_vector_records_16")
    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "16")
    get_settings.cache_clear()

    from app.rag.bootstrap import default_vendor_ticket_documents
    from app.rag.semantic_retriever import build_in_memory_store_from_documents

    fake_store = build_in_memory_store_from_documents(default_vendor_ticket_documents())
    captured: dict[str, object] = {}

    def fake_create_vector_store(config: object) -> object:
        captured["config"] = config
        return fake_store

    monkeypatch.setattr("app.nodes.common.create_vector_store", fake_create_vector_store)

    out = retrieve_context(_base_state())
    from app.rag.vector_store_factory import VectorStoreConfig

    config = captured["config"]
    assert isinstance(config, VectorStoreConfig)
    assert config.table_name == "rag_vector_records_16"
    assert config.dimensions == 16

    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["rag_profile"] == "semantic_pgvector_16"
    assert rwf["requested_strategy"] == "semantic"
    assert rwf["effective_strategy"] == "semantic"
    assert rwf["vector_store_provider"] == "pgvector"
    assert rwf["pgvector_table"] == "rag_vector_records_16"
    assert rwf["pgvector_dimensions"] == 16

    audit = _retrieve_context_audit(out)
    assert audit["vector_store_provider"] == "pgvector"
    assert audit["pgvector_table"] == "rag_vector_records_16"
    assert audit["pgvector_dimensions"] == 16

    response = _serialize_state(out)
    summary = response.retrieval_summary
    assert summary["vector_store_provider"] == "pgvector"
    assert summary["pgvector_table"] == "rag_vector_records_16"
    assert summary["pgvector_dimensions"] == 16
    _assert_no_secrets(summary)
    assert "postgresql" not in str(summary).lower()
    assert "database_url" not in summary


def test_semantic_pgvector_profile_retrieval_summary_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_pgvector")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pgvector")
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setenv("PGVECTOR_TABLE", "rag_vector_records")
    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "1536")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    get_settings.cache_clear()

    from app.rag.bootstrap import default_vendor_ticket_documents
    from app.rag.semantic_retriever import build_in_memory_store_from_documents

    fake_store = build_in_memory_store_from_documents(default_vendor_ticket_documents())

    monkeypatch.setattr(
        "app.nodes.common.create_vector_store",
        lambda _config: fake_store,
    )

    out = retrieve_context(_base_state())
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["rag_profile"] == "semantic_pgvector"
    assert rwf["vector_store_provider"] == "pgvector"
    assert rwf["pgvector_table"] == "rag_vector_records"
    assert rwf["pgvector_dimensions"] == 1536
    assert rwf["embedding_provider"] == "openai"
    assert rwf["embedding_model"] == "text-embedding-3-small"

    response = _serialize_state(out)
    summary = response.retrieval_summary
    assert summary["rag_profile"] == "semantic_pgvector"
    assert summary["pgvector_table"] == "rag_vector_records"
    assert summary["pgvector_dimensions"] == 1536
    _assert_no_secrets(summary)
    assert "database_url" not in summary
    assert "postgresql" not in str(summary).lower()


def test_semantic_pgvector_16_create_store_failure_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PROFILE", "semantic_pgvector_16")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pgvector")
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setenv("PGVECTOR_TABLE", "rag_vector_records_16")
    monkeypatch.setenv("PGVECTOR_DIMENSIONS", "16")
    get_settings.cache_clear()

    def _raise_create(_config: object) -> object:
        raise RuntimeError("pgvector unavailable")

    monkeypatch.setattr("app.nodes.common.create_vector_store", _raise_create)

    out = retrieve_context(_base_state())
    assert any(e.error_type == "rag_strategy_error" for e in out["errors"])
    rwf = out["tool_results"]["retrieve_for_workflow"]
    assert rwf["effective_strategy"] == "mock"
    assert rwf["rag_profile"] == "semantic_pgvector_16"
