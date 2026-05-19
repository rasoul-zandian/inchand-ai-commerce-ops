"""Tests for shadow vendor-ticket AI operational assist (HITL-only, no retrieval content)."""

from __future__ import annotations

import json

import pytest
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistActionType
from app.workflows.vendor_ticket_ai_assist_shadow import (
    assert_ai_assist_input_safe,
    evaluate_vendor_ticket_ai_assist_shadow,
)


def _base_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ticket_id": "t-001",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "review_priority": "LOW",
        "retrieval_gate_decision": "allow",
        "retrieval_result_count": 5,
        "retrieval_query_hash": "abc123hash",
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "retrieval_sandbox_only": True,
    }
    row.update(overrides)
    return row


def test_support_case_monitor_action() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(_base_row())
    assert result.suggested_action == VendorTicketAIAssistActionType.MONITOR
    assert result.escalation_recommended is False
    assert result.retrieval_summary_available is True
    assert result.assist_shadow_only is True
    assert result.human_review_required is True
    assert result.retrieval_activated is False
    assert result.downstream_consumed_retrieval is False


def test_complaint_case_escalation_recommended() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        _base_row(ticket_label="complaint", route_label="escalation_review"),
    )
    assert result.escalation_recommended is True
    assert result.suggested_action == VendorTicketAIAssistActionType.ESCALATE
    assert any(s.action_type == VendorTicketAIAssistActionType.ESCALATE for s in result.suggestions)


def test_fund_case_billing_review() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        _base_row(ticket_label="fund", route_label="billing_review"),
    )
    assert result.suggested_action == VendorTicketAIAssistActionType.BILLING_REVIEW
    assert any(
        s.action_type == VendorTicketAIAssistActionType.BILLING_REVIEW for s in result.suggestions
    )


def test_retrieval_metadata_absent_when_gate_not_allow() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        _base_row(retrieval_gate_decision="skip", retrieval_result_count=5),
    )
    assert result.retrieval_summary_available is False


def test_retrieval_metadata_absent_when_zero_count() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(_base_row(retrieval_result_count=0))
    assert result.retrieval_summary_available is False


def test_duplicate_possible_when_many_hits() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(_base_row(retrieval_result_count=5))
    assert result.duplicate_possible is True


def test_rejects_forbidden_user_input() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        evaluate_vendor_ticket_ai_assist_shadow(_base_row(user_input="secret transcript"))


def test_rejects_draft_and_final_response() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        evaluate_vendor_ticket_ai_assist_shadow(_base_row(draft_response="hello customer"))


def test_rejects_retrieval_activated_true() -> None:
    with pytest.raises(ValueError, match="retrieval_activated"):
        evaluate_vendor_ticket_ai_assist_shadow(_base_row(retrieval_activated=True))


def test_output_has_no_customer_reply_fields() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(_base_row())
    dumped = json.loads(result.model_dump_json())
    forbidden = {
        "user_input",
        "final_response",
        "draft_response",
        "content",
        "results",
        "query",
        "customer_reply",
        "generated_response",
    }
    keys: set[str] = set()

    def collect(obj: object) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                keys.add(str(key).lower())
                collect(val)
        elif isinstance(obj, list):
            for item in obj:
                collect(item)

    collect(dumped)
    assert keys.isdisjoint(forbidden)


def test_suggestion_summaries_are_short_safe_strings() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(_base_row())
    for suggestion in result.suggestions:
        assert len(suggestion.summary) <= 240
        assert "customer" not in suggestion.summary.lower() or "no autonomous customer" in (
            suggestion.summary.lower()
        )


def test_assert_safe_on_results_key() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_ai_assist_input_safe({"results": [{"content": "leak"}]})
