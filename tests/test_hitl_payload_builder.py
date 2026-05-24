"""Tests for HITL read-only panel payload builder."""

from __future__ import annotations

import pytest
from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
    build_hitl_read_only_payload_from_state,
)
from app.hitl.hitl_visibility_contract import assert_hitl_visible_payload_safe


def _safe_state() -> dict[str, object]:
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
        "retrieval_metadata_filter": {
            "ticket_label": "fund",
            "route_label": "billing_review",
            "review_priority": "LOW",
        },
        "retrieval_sandbox_only": True,
        "retrieval_activated": False,
    }


def _safe_replay_row() -> dict[str, object]:
    row = dict(_safe_state())
    row["errors"] = []
    row["downstream_consumed_retrieval"] = False
    return row


def test_builds_valid_payload_from_safe_state() -> None:
    payload = build_hitl_read_only_payload_from_state(_safe_state())
    assert_hitl_payload_ready(payload)
    assert payload["room_id"] == "ROOM_1"
    assert payload["retrieval_metadata_filter"] == {
        "ticket_label": "fund",
        "route_label": "billing_review",
    }
    assert "review_priority" not in (payload.get("retrieval_metadata_filter") or {})


def test_builds_valid_payload_from_replay_row() -> None:
    payload = build_hitl_read_only_payload_from_replay_row(_safe_replay_row())
    assert_hitl_payload_ready(payload)
    assert "errors" not in payload
    assert "downstream_consumed_retrieval" not in payload


def test_preserves_intent_taxonomy_fields() -> None:
    row = {
        **_safe_replay_row(),
        "detected_intent": "settlement_panel_access_issue",
        "intent_confidence_band": "medium",
        "intent_reasons_summary": "keyword:تصفیه پنل",
        "intent_related_document_types": "settlement_rules",
        "extracted_order_ids": "1001,1002",
        "extracted_tracking_code": "123456789012",
    }
    payload = build_hitl_read_only_payload_from_replay_row(row)
    assert payload["detected_intent"] == "settlement_panel_access_issue"
    assert payload["intent_confidence_band"] == "medium"
    assert payload["intent_reasons_summary"] == "keyword:تصفیه پنل"
    assert payload["intent_related_document_types"] == "settlement_rules"
    assert payload["extracted_order_ids"] == "1001,1002"
    assert payload["extracted_tracking_code"] == "123456789012"


def test_rejects_forbidden_field_in_source() -> None:
    state = _safe_state()
    state["user_input"] = "secret"
    with pytest.raises(ValueError, match="forbidden keys"):
        build_hitl_read_only_payload_from_state(state)


def test_does_not_include_retrieval_query_hash() -> None:
    state = _safe_state()
    state["retrieval_query_hash"] = "abc123"
    with pytest.raises(ValueError, match="forbidden keys"):
        build_hitl_read_only_payload_from_state(state)


def test_rejects_retrieval_activated_true() -> None:
    state = _safe_state()
    state["retrieval_activated"] = True
    with pytest.raises(ValueError, match="retrieval_activated must be false"):
        build_hitl_read_only_payload_from_state(state)


def test_rejects_ai_assist_shadow_only_false() -> None:
    state = _safe_state()
    state["ai_assist_shadow_only"] = False
    with pytest.raises(ValueError, match="ai_assist_shadow_only must not be false"):
        build_hitl_read_only_payload_from_state(state)


def test_payload_passes_assert_hitl_visible_payload_safe() -> None:
    payload = build_hitl_read_only_payload_from_replay_row(_safe_replay_row())
    assert_hitl_visible_payload_safe(payload)


def test_strips_forbidden_nested_content_by_rejecting_messages_key() -> None:
    row = _safe_replay_row()
    row["messages"] = [{"text": "hello"}]
    with pytest.raises(ValueError, match="forbidden keys"):
        build_hitl_read_only_payload_from_replay_row(row)
