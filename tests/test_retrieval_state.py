"""Tests for additive retrieval fields on CommerceAIState (no execution)."""

from __future__ import annotations

import pytest
from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateResult,
    RetrievalScenario,
)
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolResponse,
    RetrievalToolResult,
)
from app.state.commerce_state import CommerceAIState
from app.state.retrieval_state import (
    RETRIEVAL_STATE_DEFAULTS,
    apply_retrieval_gate_result_to_state,
    apply_retrieval_tool_response_to_state,
    default_retrieval_state_values,
    sanitize_retrieval_state_snapshot,
)

from tests.test_vendor_ticket_workflow import make_base_state


def test_default_retrieval_state_values_are_safe() -> None:
    defaults = default_retrieval_state_values()
    assert defaults["retrieval_sandbox_only"] is True
    assert defaults["retrieval_activated"] is False
    assert defaults["retrieval_policy_reasons"] == []
    assert defaults["retrieval_query_hash"] is None
    assert RETRIEVAL_STATE_DEFAULTS["retrieval_activated"] is False


def test_make_base_state_backward_compatible_without_retrieval_keys() -> None:
    state = make_base_state()
    assert "retrieval_activated" not in state
    assert state["request_id"]
    assert state["user_input"]


def test_apply_gate_result_to_state() -> None:
    state = make_base_state()
    gate_result = RetrievalPolicyGateResult(
        decision=RetrievalGateDecision.ALLOW,
        scenario=RetrievalScenario.FUND_FINANCE,
        reasons=["retrieval_allowed for fund"],
        required_metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        retrieval_activated=False,
        sandbox_only=True,
    )
    apply_retrieval_gate_result_to_state(state, gate_result)
    assert state["retrieval_gate_decision"] == "allow"
    assert state["retrieval_scenario"] == "fund_finance"
    assert state["retrieval_policy_reasons"] == ["retrieval_allowed for fund"]
    assert state["retrieval_metadata_filter"] == {"ticket_label": "fund"}
    assert state["retrieval_sandbox_only"] is True
    assert state["retrieval_activated"] is False


def test_apply_tool_response_only_aggregate_safe_fields() -> None:
    state = make_base_state()
    response = RetrievalToolResponse(
        results=[
            RetrievalToolResult(
                record_id="pilot::ns::v1::fund-1",
                score=0.42,
                ticket_label="fund",
                route_label="billing_review",
                review_priority="high",
            )
        ],
        retrieval_activated=False,
        sandbox_only=True,
        query_hash="c24189e23ea1c12c",
        result_count=1,
    )
    apply_retrieval_tool_response_to_state(state, response)
    assert state["retrieval_query_hash"] == "c24189e23ea1c12c"
    assert state["retrieval_result_count"] == 1
    assert state["retrieval_activated"] is False
    assert "results" not in state
    assert "content" not in state
    assert "vector" not in state


def test_sanitize_retrieval_state_snapshot_strips_unsafe_metadata_keys() -> None:
    state: CommerceAIState = make_base_state()
    state["retrieval_gate_decision"] = "allow"
    state["retrieval_query_hash"] = "abc123"
    state["retrieval_result_count"] = 2
    state["retrieval_policy_reasons"] = ["ok"]
    state["retrieval_sandbox_only"] = True
    state["retrieval_activated"] = False
    state["retrieval_metadata_filter"] = {"ticket_label": "fund"}

    snapshot = sanitize_retrieval_state_snapshot(state)
    assert snapshot["retrieval_query_hash"] == "abc123"
    assert snapshot["retrieval_activated"] is False
    assert "query" not in snapshot
    assert "content" not in snapshot


def test_sanitize_rejects_forbidden_metadata_filter_keys() -> None:
    state: CommerceAIState = make_base_state()
    state["retrieval_metadata_filter"] = {"ticket_label": "fund", "content": "secret"}
    state["retrieval_activated"] = False
    state["retrieval_sandbox_only"] = True
    with pytest.raises(ValueError, match="unsupported keys|forbidden keys"):
        sanitize_retrieval_state_snapshot(state)


def test_gate_result_model_rejects_retrieval_activated_true() -> None:
    with pytest.raises(ValueError, match="retrieval_activated"):
        RetrievalPolicyGateResult(
            decision=RetrievalGateDecision.DENY,
            scenario=RetrievalScenario.UNKNOWN,
            retrieval_activated=True,
        )


def test_tool_response_model_rejects_retrieval_activated_true() -> None:
    with pytest.raises(ValueError, match="retrieval_activated"):
        RetrievalToolResponse(
            results=[],
            retrieval_activated=True,
            sandbox_only=True,
            query_hash="deadbeefdeadbeef",
            result_count=0,
        )
