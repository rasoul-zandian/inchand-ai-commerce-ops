"""Tests for review queue metadata (category, priority, API exposure)."""

from __future__ import annotations

import pytest
from app.api.main import _serialize_state, app
from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import DraftingResult, build_review_queue_metadata
from fastapi.testclient import TestClient

from tests.test_vendor_ticket_workflow import make_base_state


def test_billing_route_category_and_low_priority() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-review-billing",
    )
    meta = build_review_queue_metadata(state)
    assert meta["review_category"] == "billing"
    assert meta["review_priority"] == "LOW"
    assert meta["review_reason"] == "Billing discrepancy response awaiting approval."
    assert meta["requires_human_approval"] is True
    assert meta["route_label"] == "billing_review"


def test_qa_attention_high_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    def _risky_draft(**kwargs: object) -> DraftingResult:
        _ = kwargs
        return DraftingResult(
            draft_response="مبلغ قطعی فردا واریز می‌شود.",
            llm_provider="mock",
            llm_model="mock-vendor-ticket-drafter",
        )

    monkeypatch.setattr("app.nodes.vendor_ticket._drafting_agent", _risky_draft)
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-review-qa-high",
    )
    meta = build_review_queue_metadata(state)
    assert meta["review_category"] == "qa_attention"
    assert meta["review_priority"] == "HIGH"
    assert meta["qa_requires_attention"] is True
    assert meta["qa_issue_count"] >= 1
    assert "QA issues" in meta["review_reason"]


def test_escalation_medium_priority() -> None:
    state = make_base_state(user_input="ارجاع فوری تیکت به سطح بالاتر")
    state["route_label"] = "escalation_review"
    state["qa_requires_human_attention"] = False
    state["risk_score"] = 0.34
    state["confidence_score"] = 0.82
    state["human_approval_required"] = True

    meta = build_review_queue_metadata(state)
    assert meta["review_category"] == "escalation"
    assert meta["review_priority"] == "MEDIUM"
    assert "Escalation" in meta["review_reason"]


def test_api_includes_review_queue_metadata() -> None:
    client = TestClient(app)
    res = client.post(
        "/run-vendor-ticket",
        json={"user_input": "سلام", "ticket_id": "t-review-api"},
    )
    body = res.json()
    assert "review_queue_metadata" in body
    rq = body["review_queue_metadata"]
    assert rq["review_category"]
    assert rq["review_priority"] in {"HIGH", "MEDIUM", "LOW"}
    assert rq["review_reason"]
    assert rq["requires_human_approval"] is True
    assert body["human_approval_required"] is True


def test_serialize_state_preserves_existing_fields() -> None:
    state = run_vendor_ticket_demo("سلام", ticket_id="t-review-keys")
    response = _serialize_state(state)
    dumped = response.model_dump()
    assert "specialist_output" in dumped
    assert "qa_attention_summary" in dumped
    assert "review_queue_metadata" in dumped
    assert dumped["review_queue_metadata"]["review_category"] == "billing"
