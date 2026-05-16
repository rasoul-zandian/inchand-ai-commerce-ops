"""Automated checks for the vendor ticket LangGraph workflow (happy + failure paths)."""

from __future__ import annotations

import uuid

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.common import (
    normalize_request,
    retrieve_context,
    risk_and_approval_decision,
    validate_output,
)
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def make_base_state(
    *,
    user_input: str = "سلام، این یک پیام تست است.",
    ticket_id: str | None = "demo-ticket-001",
    request_id: str | None = None,
    session_id: str | None = None,
) -> CommerceAIState:
    """Minimal CommerceAIState for node-level tests (all required keys, neutral defaults)."""
    rid = str(uuid.uuid4()) if request_id is None else request_id
    return {
        "request_id": rid,
        "session_id": session_id,
        "user_id": None,
        "user_role": None,
        "user_input": user_input,
        "workflow_type": WorkflowType.UNKNOWN,
        "workflow_status": WorkflowStatus.STARTED,
        "entity_type": EntityType.UNKNOWN,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": ticket_id,
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


def test_vendor_ticket_workflow_happy_path() -> None:
    """End-to-end mock run should reach human approval with clean errors and tool coverage."""
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-happy-001",
    )

    assert state["workflow_type"] == WorkflowType.VENDOR_TICKET
    assert state["workflow_status"] == WorkflowStatus.AWAITING_APPROVAL
    assert state["approval_status"] == ApprovalStatus.REQUIRED
    assert state["human_approval_required"] is True
    assert state["errors"] == []

    assert state["final_response"]
    assert isinstance(state["final_response"], str)

    specialist = state["specialist_output"]
    assert "draft_response" in specialist
    assert "confidence_score" in specialist
    assert "risk_score" in specialist
    evidence = specialist.get("evidence") or []
    assert any("llm_provider=mock" in line for line in evidence)
    assert not any("llm_digest=None" in line for line in evidence)
    assert any(line.startswith("llm_digest=") for line in evidence)

    assert any(line.startswith("rag_document_count=") for line in evidence)
    rag_count_line = next(line for line in evidence if line.startswith("rag_document_count="))
    assert rag_count_line == "rag_document_count=5"
    rag_sources_line = next(line for line in evidence if line.startswith("rag_sources="))
    assert rag_sources_line == "rag_sources=approved_pattern,policy,style_guide"

    vt_audit = next(
        entry for entry in state["audit_log"] if entry.node_name == "vendor_ticket_node"
    )
    assert vt_audit.metadata.get("rag_document_count") == 5

    billing_route_audit = next(
        entry for entry in state["audit_log"] if entry.node_name == "billing_review"
    )
    assert billing_route_audit.metadata.get("route_label") == "billing_review"

    tools = state["tool_results"]
    assert "get_ticket" in tools
    assert "get_vendor_profile" in tools
    assert "search_support_policy" in tools
    assert "search_previous_ticket_responses" in tools

    assert len(state["audit_log"]) >= 7


def test_validation_failure_does_not_require_approval() -> None:
    """Invalid draft/final output must fail closed without moving to awaiting approval."""
    state = make_base_state(user_input="سلام، نیاز به بررسی دارم.", ticket_id="t-fail-001")
    state = retrieve_context(state)

    state["specialist_output"] = {}
    state["final_response"] = None

    state = validate_output(state)
    state = risk_and_approval_decision(state)

    assert state["errors"]
    assert state["workflow_status"] == WorkflowStatus.FAILED
    assert state["approval_status"] == ApprovalStatus.NOT_REQUIRED
    assert state["human_approval_required"] is False
    assert state["recommended_action"] == "fix_workflow_errors"


def test_normalize_request_sets_request_and_session_ids() -> None:
    """Empty request_id should be replaced; missing session should mirror request_id."""
    state = make_base_state(request_id="", session_id=None)
    state = normalize_request(state)

    assert state["request_id"]
    assert state["session_id"] == state["request_id"]
    assert state["workflow_status"] == WorkflowStatus.IN_PROGRESS
