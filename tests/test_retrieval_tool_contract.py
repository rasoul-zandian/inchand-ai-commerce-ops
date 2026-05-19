"""Tests for sandbox retrieval tool contract models and validation (no network)."""

from __future__ import annotations

import json

import pytest
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolRequest,
    RetrievalToolResponse,
    RetrievalToolResult,
    query_hash,
    retrieval_tool_response_to_dict,
)
from app.corpus_planning.retrieval_tool_validation import (
    assert_no_forbidden_output_fields,
    assert_safe_retrieval_tool_response,
    validate_allowed_metadata_filter,
    validate_retrieval_tool_request,
    validate_sandbox_index_version,
    validate_sandbox_namespace,
    validate_top_k,
)


def test_request_validation_accepts_balanced_scope() -> None:
    request = validate_retrieval_tool_request(
        {
            "query": " vendor settlement status ",
            "top_k": 5,
            "namespace": "vendor_ticket_real_pilot_balanced",
            "index_version": "pilot_balanced_v1",
            "metadata_filter": {"ticket_label": "fund"},
            "eval_mode": "metadata_filtered",
        }
    )
    assert request.query == "vendor settlement status"
    assert request.namespace == "vendor_ticket_real_pilot_balanced"
    assert request.metadata_filter is not None
    assert request.metadata_filter.ticket_label == "fund"


def test_forbidden_metadata_keys_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        validate_allowed_metadata_filter(
            {"ticket_label": "fund", "namespace": "vendor_ticket_real_pilot"}
        )
    with pytest.raises(ValueError, match="forbidden keys"):
        validate_allowed_metadata_filter(
            {"route_label": "billing_review", "index_version": "pilot_v1"}
        )
    with pytest.raises(ValueError, match="forbidden keys"):
        validate_allowed_metadata_filter({"department": "finance"})


def test_arbitrary_metadata_key_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported keys"):
        validate_allowed_metadata_filter({"ticket_label": "fund", "room_id": "ROOM_1"})


def test_metadata_filter_requires_allowed_field() -> None:
    with pytest.raises(ValueError, match="at least one"):
        validate_allowed_metadata_filter({})


def test_sandbox_namespace_enforcement() -> None:
    assert validate_sandbox_namespace("vendor_ticket_real_pilot_balanced") == (
        "vendor_ticket_real_pilot_balanced"
    )
    with pytest.raises(ValueError, match="approved sandbox"):
        validate_sandbox_namespace("production_corpus")


def test_index_version_must_be_pilot_prefixed() -> None:
    assert validate_sandbox_index_version("pilot_balanced_v1") == "pilot_balanced_v1"
    with pytest.raises(ValueError, match="pilot_"):
        validate_sandbox_index_version("v1")


def test_top_k_bounds() -> None:
    assert validate_top_k(1) == 1
    assert validate_top_k(50) == 50
    with pytest.raises(ValueError, match="top_k must be"):
        validate_top_k(0)
    with pytest.raises(ValueError, match="top_k must be"):
        validate_top_k(51)


def test_response_serialization_safety() -> None:
    response = RetrievalToolResponse(
        results=[
            RetrievalToolResult(
                record_id="pilot::vendor_ticket_real_pilot_balanced::pilot_balanced_v1::doc-1",
                score=0.42,
                ticket_label="fund",
                route_label="billing_review",
                review_priority="normal",
            )
        ],
        query_hash=query_hash("vendor settlement"),
        result_count=1,
    )
    payload = retrieval_tool_response_to_dict(response)
    assert payload["retrieval_activated"] is False
    assert payload["sandbox_only"] is True
    assert_safe_retrieval_tool_response(response)
    serialized = json.dumps(payload)
    assert "conversation_transcript" not in serialized
    assert '"vector"' not in serialized


def test_forbidden_output_fields_detected() -> None:
    with pytest.raises(ValueError, match="forbidden JSON keys"):
        assert_no_forbidden_output_fields(
            {
                "results": [{"record_id": "x", "content": "secret"}],
                "retrieval_activated": False,
            }
        )


def test_response_rejects_activation_flags() -> None:
    query_fingerprint = query_hash("sandbox test query")
    with pytest.raises(ValueError, match="retrieval_activated must be false"):
        RetrievalToolResponse(
            results=[],
            retrieval_activated=True,
            sandbox_only=True,
            query_hash=query_fingerprint,
            result_count=0,
        )
    with pytest.raises(ValueError, match="sandbox_only must be true"):
        RetrievalToolResponse(
            results=[],
            retrieval_activated=False,
            sandbox_only=False,
            query_hash=query_fingerprint,
            result_count=0,
        )


def test_request_extra_fields_forbidden() -> None:
    with pytest.raises(ValueError):
        RetrievalToolRequest.model_validate(
            {
                "query": "test",
                "top_k": 3,
                "namespace": "vendor_ticket_real_pilot",
                "index_version": "pilot_v1",
                "profile": "semantic_pgvector",
            }
        )


def test_result_extra_fields_forbidden() -> None:
    with pytest.raises(ValueError):
        RetrievalToolResult.model_validate(
            {
                "record_id": "pilot::x",
                "score": 0.1,
                "ticket_label": "fund",
                "route_label": "billing_review",
                "review_priority": "normal",
                "document_id": "doc-1",
            }
        )
