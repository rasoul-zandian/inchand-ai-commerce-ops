"""Tests for observability-only conditional routing after vendor_ticket_node."""

from __future__ import annotations

import pytest
from app.api.main import app
from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.common import retrieve_context
from app.nodes.route_observability import (
    billing_review_node,
    general_vendor_review_node,
    qa_attention_review_node,
    route_after_vendor_ticket,
)
from app.nodes.vendor_ticket import DraftingResult, vendor_ticket_node
from app.schemas.workflow import ApprovalStatus, WorkflowStatus
from fastapi.testclient import TestClient

from tests.test_vendor_ticket_workflow import make_base_state


def test_route_after_vendor_ticket_labels() -> None:
    assert route_after_vendor_ticket({"route_label": "qa_attention"}) == "qa_attention_review"
    assert route_after_vendor_ticket({"route_label": "escalation_review"}) == "escalation_review"
    assert route_after_vendor_ticket({"route_label": "billing_review"}) == "billing_review"
    assert route_after_vendor_ticket({"route_label": "style_guidance"}) == "style_guidance_review"
    assert route_after_vendor_ticket({"route_label": None}) == "general_vendor_review"
    assert route_after_vendor_ticket({"route_label": "unknown"}) == "general_vendor_review"


def test_qa_attention_review_sets_flag_and_audit_metadata() -> None:
    state = make_base_state()
    state["route_label"] = "qa_attention"
    state["qa_passed"] = False
    state["routing_reasons"] = ["qa_issues_present"]
    state["qa_issues"] = ["risky_promise_language:مبلغ قطعی"]
    state["qa_warnings"] = ["billing_missing_clarification_request"]
    state["specialist_recommended_action"] = "review_qa_issues_before_reply"
    state = qa_attention_review_node(state)
    assert state["qa_requires_human_attention"] is True
    entry = next(e for e in state["audit_log"] if e.node_name == "qa_attention_review")
    assert entry.message == "QA attention route reviewed before validation."
    assert entry.metadata.get("qa_passed") is False
    assert entry.metadata.get("qa_issue_count") == 1
    assert entry.metadata.get("qa_warning_count") == 1
    assert entry.metadata.get("qa_issues") == ["risky_promise_language:مبلغ قطعی"]
    assert entry.metadata.get("route_label") == "qa_attention"


def test_billing_review_does_not_set_qa_attention_flag() -> None:
    state = make_base_state()
    state["route_label"] = "billing_review"
    state = billing_review_node(state)
    assert state.get("qa_requires_human_attention") is False


def test_qa_attention_graph_path_reaches_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    def _risky_draft(**kwargs: object) -> DraftingResult:
        _ = kwargs
        return DraftingResult(
            draft_response="مبلغ قطعی فردا واریز می‌شود.",
            llm_provider="mock",
            llm_model="mock-vendor-ticket-drafter",
            llm_metadata={"digest": "qa-test"},
        )

    monkeypatch.setattr("app.nodes.vendor_ticket._drafting_agent", _risky_draft)
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-qa-attention-001",
    )
    assert state["route_label"] == "qa_attention"
    assert state["qa_requires_human_attention"] is True
    assert state["workflow_status"] == WorkflowStatus.AWAITING_APPROVAL
    assert state["human_approval_required"] is True
    qa_audit = next(e for e in state["audit_log"] if e.node_name == "qa_attention_review")
    assert qa_audit.metadata.get("qa_issue_count", 0) >= 1
    risk_audit = next(e for e in state["audit_log"] if e.node_name == "risk_and_approval_decision")
    assert risk_audit.metadata.get("qa_requires_human_attention") is True
    evidence = state["specialist_output"].get("evidence") or []
    assert any(line == "qa_attention_required=true" for line in evidence)


def test_qa_attention_review_does_not_mutate_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    def _risky_draft(**kwargs: object) -> DraftingResult:
        _ = kwargs
        return DraftingResult(
            draft_response="مبلغ قطعی فردا واریز می‌شود.",
            llm_provider="mock",
            llm_model="mock-vendor-ticket-drafter",
        )

    monkeypatch.setattr("app.nodes.vendor_ticket._drafting_agent", _risky_draft)
    state = make_base_state()
    state = retrieve_context(state)
    state = vendor_ticket_node(state)
    draft = state["specialist_output"]["draft_response"]
    final = state["final_response"]
    state = qa_attention_review_node(state)
    assert state["specialist_output"]["draft_response"] == draft
    assert state["final_response"] == final


def test_billing_review_node_does_not_mutate_draft_fields() -> None:
    state = make_base_state()
    state = retrieve_context(state)
    state = vendor_ticket_node(state)
    draft = state["specialist_output"]["draft_response"]
    risk = state["risk_score"]
    final = state["final_response"]
    state = billing_review_node(state)
    assert state["specialist_output"]["draft_response"] == draft
    assert state["risk_score"] == risk
    assert state["final_response"] == final


def test_happy_path_includes_billing_review_observability_audit() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-route-graph-001",
    )
    assert state["route_label"] == "billing_review"
    billing_audit = next(e for e in state["audit_log"] if e.node_name == "billing_review")
    assert billing_audit.metadata.get("route_label") == "billing_review"
    assert state["workflow_status"] == WorkflowStatus.AWAITING_APPROVAL
    assert state["approval_status"] == ApprovalStatus.REQUIRED
    assert state["human_approval_required"] is True
    assert state["recommended_action"] == "review_ticket_reply_draft"


def test_general_vendor_review_for_missing_route_label() -> None:
    state = make_base_state()
    state["route_label"] = None
    state = general_vendor_review_node(state)
    entry = next(e for e in state["audit_log"] if e.node_name == "general_vendor_review")
    assert entry.metadata.get("route_label") is None


def test_fastapi_response_shape_unchanged() -> None:
    client = TestClient(app)
    res = client.post(
        "/run-vendor-ticket",
        json={
            "user_input": "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
            "ticket_id": "t-api-route",
        },
    )
    assert res.status_code == 200
    body = res.json()
    expected_keys = {
        "request_id",
        "session_id",
        "workflow_type",
        "workflow_status",
        "approval_status",
        "human_approval_required",
        "recommended_action",
        "final_response",
        "specialist_output",
        "tool_results",
        "retrieval_summary",
        "qa_attention_summary",
        "review_queue_metadata",
        "errors",
        "audit_log",
    }
    assert set(body.keys()) == expected_keys
