"""Tests for department-aware review routing contract."""

from __future__ import annotations

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import build_review_queue_metadata
from app.review_queue import build_review_queue_item
from app.review_queue.department_routing import build_department_review_route

from tests.test_vendor_ticket_workflow import make_base_state


def test_fund_ticket_label_routes_finance() -> None:
    route = build_department_review_route(
        ticket_label="fund",
        route_label="billing_review",
        qa_requires_human_attention=False,
        risk_score=0.2,
    )
    assert route.assigned_department == "finance"


def test_support_label_not_finance_when_route_general() -> None:
    route = build_department_review_route(
        ticket_label="support",
        route_label="general_vendor_support",
        qa_requires_human_attention=False,
        risk_score=0.2,
        detected_intent="general_vendor_support",
    )
    assert route.assigned_department == "support"


def test_financial_ticket_label_routes_finance() -> None:
    route = build_department_review_route(
        ticket_label="financial",
        route_label=None,
        qa_requires_human_attention=False,
        risk_score=0.2,
    )
    assert route.assigned_department == "finance"
    assert route.reviewer_role == "finance_operator"


def test_persian_mali_routes_finance() -> None:
    route = build_department_review_route(
        ticket_label="مالی",
        route_label=None,
        qa_requires_human_attention=False,
        risk_score=None,
    )
    assert route.assigned_department == "finance"


def test_support_persian_routes_support() -> None:
    route = build_department_review_route(
        ticket_label="پشتیبانی",
        route_label=None,
        qa_requires_human_attention=False,
        risk_score=None,
    )
    assert route.assigned_department == "support"
    assert route.reviewer_role == "support_operator"


def test_complaint_routes_complaint() -> None:
    route = build_department_review_route(
        ticket_label="شکایت",
        route_label=None,
        qa_requires_human_attention=False,
        risk_score=None,
    )
    assert route.assigned_department == "complaint"
    assert route.reviewer_role == "complaint_operator"


def test_qa_attention_routes_senior_qa_review() -> None:
    route = build_department_review_route(
        ticket_label="financial",
        route_label="qa_attention",
        qa_requires_human_attention=True,
        risk_score=0.2,
    )
    assert route.assigned_department == "qa_review"
    assert route.reviewer_role == "senior_reviewer"
    assert route.requires_senior_review is True


def test_high_risk_routes_senior_qa_review() -> None:
    route = build_department_review_route(
        ticket_label="support",
        route_label="general_vendor_support",
        qa_requires_human_attention=False,
        risk_score=0.7,
    )
    assert route.assigned_department == "qa_review"
    assert route.reviewer_role == "senior_reviewer"


def test_billing_review_route_label_finance() -> None:
    route = build_department_review_route(
        ticket_label=None,
        route_label="billing_review",
        qa_requires_human_attention=False,
        risk_score=0.3,
    )
    assert route.assigned_department == "finance"


def test_escalation_defaults_support_unless_complaint() -> None:
    support_route = build_department_review_route(
        ticket_label="financial",
        route_label="escalation_review",
        qa_requires_human_attention=False,
        risk_score=0.3,
    )
    assert support_route.assigned_department == "support"

    complaint_route = build_department_review_route(
        ticket_label="complaint",
        route_label="escalation_review",
        qa_requires_human_attention=False,
        risk_score=0.3,
    )
    assert complaint_route.assigned_department == "complaint"


def test_review_queue_metadata_includes_department_route() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-dept-meta",
    )
    meta = build_review_queue_metadata(state)
    dept = meta["department_route"]
    assert dept["assigned_department"] == "finance"
    assert dept["reviewer_role"] == "finance_operator"


def test_review_queue_item_metadata_includes_department_route() -> None:
    state = run_vendor_ticket_demo("سلام", ticket_id="t-dept-item")
    item = build_review_queue_item(state)
    assert "department_route" in item.metadata
    assert item.metadata["department_route"]["assigned_department"]


def test_state_without_ticket_label_uses_detected_intent_fallback() -> None:
    state = make_base_state(user_input="تسویه")
    state["detected_intent"] = "billing_discrepancy"
    state["route_label"] = "billing_review"
    state["human_approval_required"] = True
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "finance"
