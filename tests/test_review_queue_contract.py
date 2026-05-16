"""Tests for review-queue persistence contract (schema-only)."""

from __future__ import annotations

import json

from app.graph.main_graph import run_vendor_ticket_demo
from app.review_queue import (
    NoOpReviewQueueAdapter,
    ReviewQueueAdapter,
    ReviewQueueItem,
    build_review_queue_item,
)
from app.schemas.workflow import WorkflowType

from tests.test_vendor_ticket_workflow import make_base_state


def test_review_queue_item_model_fields() -> None:
    item = ReviewQueueItem(
        review_item_id="rid-1",
        workflow_type=WorkflowType.VENDOR_TICKET.value,
        workflow_run_id="run-1",
        room_id="room-1",
        review_category="billing",
        review_priority="LOW",
        review_reason="Billing discrepancy response awaiting approval.",
        requires_human_approval=True,
        route_label="billing_review",
        qa_requires_attention=False,
        qa_issue_count=0,
        risk_score=0.2,
        confidence_score=0.9,
        metadata={"detected_intent": "billing_discrepancy"},
    )
    assert item.review_item_id == "rid-1"
    assert item.workflow_type == "vendor_ticket"
    assert item.created_at.tzinfo is not None


def test_build_review_queue_item_from_workflow_state() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-contract-1",
    )
    item = build_review_queue_item(state)
    assert item.review_item_id
    assert item.workflow_run_id == state["request_id"]
    assert item.review_category == "billing"
    assert item.requires_human_approval is True
    assert item.created_at.tzinfo is not None
    assert "detected_intent" in item.metadata or "ticket_id" in item.metadata


def test_metadata_excludes_draft_and_secrets() -> None:
    state = make_base_state(user_input="سلام")
    state["human_approval_required"] = True
    state["route_label"] = "billing_review"
    state["detected_intent"] = "billing_discrepancy"
    state["qa_summary"] = "QA passed with warnings."
    state["routing_reasons"] = ["billing_keywords"]
    state["specialist_output"] = {
        "draft_response": "متن پیش‌نویس محرمانه",
        "api_key": "sk-secret",
    }
    state["retrieved_context"] = {"chunks": ["large payload"]}
    state["final_response"] = "should not appear"

    item = build_review_queue_item(state)
    dumped = json.dumps(item.model_dump(mode="json"))
    assert "draft_response" not in dumped
    assert "sk-secret" not in dumped
    assert "large payload" not in dumped
    assert "متن پیش‌نویس" not in dumped
    assert item.metadata.get("detected_intent") == "billing_discrepancy"
    assert item.metadata.get("routing_reasons") == ["billing_keywords"]


def test_noop_adapter_enqueue_and_healthcheck() -> None:
    adapter = NoOpReviewQueueAdapter()
    item = ReviewQueueItem(
        review_item_id="rid-noop",
        workflow_type="vendor_ticket",
        review_category="general_support",
        review_priority="LOW",
        review_reason="General vendor support approval required.",
        requires_human_approval=True,
    )
    adapter.enqueue_review_item(item)
    assert adapter.healthcheck() is True
    assert isinstance(adapter, ReviewQueueAdapter)


def test_persist_trace_records_review_contract_without_enqueue() -> None:
    state = run_vendor_ticket_demo("سلام", ticket_id="t-contract-trace")
    trace_entry = next(e for e in state["audit_log"] if e.node_name == "persist_trace")
    assert trace_entry.metadata.get("review_item_id")
    contract = trace_entry.metadata.get("review_item_contract")
    assert isinstance(contract, dict)
    assert contract.get("review_category")
    assert "draft_response" not in json.dumps(contract)
