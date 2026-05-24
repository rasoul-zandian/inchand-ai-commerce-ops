"""Tests for HITL read-only visibility contract (governance only)."""

from __future__ import annotations

import pytest
from app.hitl.hitl_visibility_contract import (
    HITLReadOnlyVisibilityContract,
    assert_hitl_reviewer_action_allowed,
    assert_hitl_visible_payload_safe,
    hitl_visibility_ready_for_ui,
)
from pydantic import ValidationError


def _safe_payload() -> dict[str, object]:
    return {
        "room_id": "ROOM_1",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "review_priority": "LOW",
        "assigned_department": "billing",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_priority": "low",
        "ai_assist_escalation_recommended": False,
        "ai_assist_duplicate_possible": True,
        "ai_assist_suggested_action": "billing_review",
        "ai_assist_confidence_band": "high",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_gate_decision": "allow",
        "retrieval_scenario": "fund_finance",
        "retrieval_result_count": 5,
        "retrieval_metadata_filter": {"ticket_label": "fund", "route_label": "billing_review"},
        "retrieval_sandbox_only": True,
        "retrieval_activated": False,
        "ticket_text_preview": "Seller asked about payout timing.",
    }


def _read_only_contract(**overrides: object) -> HITLReadOnlyVisibilityContract:
    base: dict[str, object] = {
        "visibility_mode": "read_only",
        "customer_facing": False,
        "auto_send_allowed": False,
        "draft_consumption_allowed": False,
        "retrieval_content_visible": False,
        "human_review_required": True,
    }
    base.update(overrides)
    return HITLReadOnlyVisibilityContract.model_validate(base)


def test_allowed_fields_accepted() -> None:
    assert_hitl_visible_payload_safe(_safe_payload())


def test_forbidden_user_input_rejected() -> None:
    payload = _safe_payload()
    payload["user_input"] = "secret transcript"
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_hitl_visible_payload_safe(payload)


def test_forbidden_draft_response_rejected() -> None:
    payload = _safe_payload()
    payload["draft_response"] = "hello customer"
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_hitl_visible_payload_safe(payload)


def test_forbidden_results_rejected() -> None:
    payload = _safe_payload()
    payload["results"] = [{"content": "hit body"}]
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_hitl_visible_payload_safe(payload)


def test_retrieval_activated_true_rejected() -> None:
    payload = _safe_payload()
    payload["retrieval_activated"] = True
    with pytest.raises(ValueError, match="retrieval_activated must be false"):
        assert_hitl_visible_payload_safe(payload)


def test_reviewer_action_allowed() -> None:
    assert_hitl_reviewer_action_allowed("view")
    assert_hitl_reviewer_action_allowed("add_internal_note")


def test_forbidden_reviewer_action_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        assert_hitl_reviewer_action_allowed("auto_send")
    with pytest.raises(ValueError, match="forbidden"):
        assert_hitl_reviewer_action_allowed("approve_customer_response")


def test_unknown_reviewer_action_rejected() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        assert_hitl_reviewer_action_allowed("unknown_action")


def test_hitl_visibility_ready_for_ui_when_safe() -> None:
    assert hitl_visibility_ready_for_ui(_read_only_contract()) is True


def test_hitl_visibility_not_ready_when_customer_facing() -> None:
    assert hitl_visibility_ready_for_ui(_read_only_contract(customer_facing=True)) is False


def test_hitl_visibility_not_ready_when_auto_send() -> None:
    assert hitl_visibility_ready_for_ui(_read_only_contract(auto_send_allowed=True)) is False


def test_hitl_visibility_not_ready_when_draft_consumption() -> None:
    contract = _read_only_contract(draft_consumption_allowed=True)
    assert hitl_visibility_ready_for_ui(contract) is False


def test_hitl_visibility_not_ready_when_retrieval_content_visible() -> None:
    contract = _read_only_contract(retrieval_content_visible=True)
    assert hitl_visibility_ready_for_ui(contract) is False


def test_hitl_visibility_not_ready_when_human_review_not_required() -> None:
    assert hitl_visibility_ready_for_ui(_read_only_contract(human_review_required=False)) is False


def test_contract_rejects_non_read_only_visibility_mode() -> None:
    with pytest.raises(ValidationError, match="visibility_mode must be read_only"):
        HITLReadOnlyVisibilityContract(visibility_mode="editable")
