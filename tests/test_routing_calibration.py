"""Routing calibration after real-ticket replay (intent + department, no LLM)."""

from __future__ import annotations

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import (
    PolicyGroundingResult,
    QACheckResult,
    _supervisor_router_agent,
    _ticket_intent_agent,
    build_review_queue_metadata,
)
from app.review_queue.department_routing import build_department_review_route


def test_support_label_generic_text_not_billing() -> None:
    intent = _ticket_intent_agent(
        ticket_subject="درخواست راهنمایی",
        ticket_body="لطفاً راهنمایی کنید",
        user_input="سلام، وضعیت سفارش را بررسی کنید",
        ticket_label="support",
    )
    assert intent.detected_intent == "general_vendor_support"
    routing = _supervisor_router_agent(
        intent=intent,
        grounding=PolicyGroundingResult(grounding_summary="policy: x", rag_document_count=1),
        qa=QACheckResult(qa_passed=True, qa_summary="passed"),
    )
    assert routing.route_label == "general_vendor_support"
    dept = build_department_review_route(
        ticket_label="support",
        route_label=routing.route_label,
        qa_requires_human_attention=False,
        risk_score=0.3,
        detected_intent=intent.detected_intent,
    )
    assert dept.assigned_department == "support"


def test_fund_label_routes_finance() -> None:
    intent = _ticket_intent_agent(
        ticket_subject="موضوع",
        ticket_body="متن",
        user_input="سلام",
        ticket_label="fund",
    )
    assert intent.detected_intent == "billing_discrepancy"
    dept = build_department_review_route(
        ticket_label="fund",
        route_label="billing_review",
        qa_requires_human_attention=False,
        risk_score=0.3,
        detected_intent=intent.detected_intent,
    )
    assert dept.assigned_department == "finance"


def test_financial_keywords_route_billing_and_finance() -> None:
    intent = _ticket_intent_agent(
        ticket_subject="تسویه",
        ticket_body="مغایرت فاکتور",
        user_input="سلام",
        ticket_label=None,
    )
    assert intent.detected_intent == "billing_discrepancy"
    routing = _supervisor_router_agent(
        intent=intent,
        grounding=PolicyGroundingResult(
            grounding_summary="policy: x",
            grounding_sources=["policy"],
            rag_document_count=1,
        ),
        qa=QACheckResult(qa_passed=True, qa_summary="passed"),
    )
    assert routing.route_label == "billing_review"
    dept = build_department_review_route(
        ticket_label=None,
        route_label=routing.route_label,
        qa_requires_human_attention=False,
        risk_score=0.3,
        detected_intent=intent.detected_intent,
    )
    assert dept.assigned_department == "finance"


def test_complaint_label_routes_complaint_department() -> None:
    intent = _ticket_intent_agent(
        ticket_subject="شکایت",
        ticket_body="اعتراض",
        user_input="سلام",
        ticket_label="complaint",
    )
    assert intent.detected_intent == "general_vendor_support"
    dept = build_department_review_route(
        ticket_label="complaint",
        route_label="general_vendor_support",
        qa_requires_human_attention=False,
        risk_score=0.2,
        detected_intent=intent.detected_intent,
    )
    assert dept.assigned_department == "complaint"


def test_missing_label_no_keywords_defaults_general_not_finance() -> None:
    intent = _ticket_intent_agent(
        ticket_subject="سلام",
        ticket_body="وضعیت سفارش",
        user_input="لطفاً بررسی کنید",
        ticket_label=None,
    )
    assert intent.detected_intent == "general_vendor_support"
    routing = _supervisor_router_agent(
        intent=intent,
        grounding=PolicyGroundingResult(grounding_summary="policy: x", rag_document_count=1),
        qa=QACheckResult(qa_passed=True, qa_summary="passed"),
    )
    assert routing.route_label == "general_vendor_support"
    dept = build_department_review_route(
        ticket_label=None,
        route_label=routing.route_label,
        qa_requires_human_attention=False,
        risk_score=0.3,
        detected_intent=intent.detected_intent,
    )
    assert dept.assigned_department == "general"


def test_workflow_support_label_end_to_end() -> None:
    state = run_vendor_ticket_demo(
        "سلام، لطفاً وضعیت سفارش را بررسی کنید",
        ticket_id="t-cal-support",
        ticket_label="support",
    )
    assert state["detected_intent"] == "general_vendor_support"
    assert state["route_label"] == "general_vendor_support"
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "support"
