"""Tests for deterministic mock operational draft templates."""

from __future__ import annotations

import re

from app.agentic_sandbox.agentic_graph import (
    initial_state_from_ticket,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.evals.draft_completion_calibration import detect_unnecessary_followup_in_draft
from app.evals.offline_draft_generation import assert_draft_reply_safe
from app.operator_console.console_models import OperatorTicket


def test_missing_identifier_draft_requests_order_id() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent="product_approval_review",
            suggested_action="check_product_approval",
            seller_text="لطفاً تایید کالا را بررسی کنید",
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "product_id",
                "requires_identifier_request": True,
                "requested_action": "check_product_approval",
            },
        ),
    )
    assert "شناسه کالا" in draft
    assert_draft_reply_safe(draft)
    assert "خروجی آزمایشی" not in draft


def test_settlement_informational_draft_is_concise() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent="settlement_status_inquiry",
            suggested_action="check_settlement_status",
            seller_text="زمان تسویه چه زمانی است؟",
            order_ids=("1234567",),
            actionability={
                "actionability_actionable": True,
                "actionability_missing_entities": "",
                "requires_identifier_request": False,
            },
        ),
    )
    assert "تسویه" in draft
    assert len(draft) <= 300
    assert not detect_unnecessary_followup_in_draft(
        draft,
        seller_text="زمان تسویه چه زمانی است؟",
        suggested_action="check_settlement_status",
        detected_intent="settlement_status_inquiry",
    )


def test_complaint_draft_without_mock_placeholder() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent="complaint_escalation",
            suggested_action="escalate",
            seller_text="شکایت من هنوز بسته نشده",
            order_ids=("7654321",),
            actionability={
                "actionability_actionable": True,
                "requires_identifier_request": False,
            },
        ),
    )
    assert "شکایت" in draft
    assert "خروجی آزمایشی" not in draft
    assert_draft_reply_safe(draft)


def test_no_hallucinated_order_ids_when_missing() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent="order_status_review",
            suggested_action="check_order_status",
            seller_text="وضعیت سفارش را بگویید",
            order_ids=(),
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "order_id",
                "requires_identifier_request": True,
            },
        ),
    )
    assert "شماره سفارش" in draft
    assert not re.search(r"\b\d{6,}\b", draft)


def test_sandbox_workflow_mock_provider_uses_realistic_draft() -> None:
    ticket = OperatorTicket(
        room_id="MOCK-DRAFT-1",
        ticket_label="fund",
        route_label="billing_review",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview="زمان تسویه سفارش چه زمانی است؟",
        latest_vendor_message=None,
        recent_context_preview=None,
    )
    initial = initial_state_from_ticket(ticket, llm_provider="mock")
    settings = (
        __import__("app.config", fromlist=["get_settings"])
        .get_settings()
        .model_copy(update={"knowledge_hints_enabled": False})
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    draft = final.get("draft_reply") or ""
    assert draft
    assert "خروجی آزمایشی" not in draft
    assert_draft_reply_safe(draft)
