"""Tests for informational draft reply completion calibration."""

from __future__ import annotations

from app.evals.draft_completion_calibration import (
    apply_draft_completion_calibration,
    build_completion_calibration_instruction,
    detect_unnecessary_followup_in_draft,
    detect_unnecessary_followup_sentence,
    draft_requires_operational_followup,
    is_informational_question,
    strip_unnecessary_trailing_followup,
)
from app.evals.draft_style import merge_style_and_completion_instructions
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_SETTLEMENT_TIMING_QUESTION = "بعد از خرید کالا توسط مشتری، چند روز دیگه میتونم تسویه کنم؟"
_SETTLEMENT_DRAFT_WITH_FILLER = (
    "تسویه مبلغ ناشی از فروش کالا، ۳ روز پس از نهایی شدن سفارش انجام می‌شود. "
    "لطفا کمی صبر کنید تا بررسی لازم انجام شود."
)
_SETTLEMENT_DRAFT_CLEAN = "تسویه مبلغ ناشی از فروش کالا، ۳ روز پس از نهایی شدن سفارش انجام می‌شود."


def test_settlement_timing_question_is_informational() -> None:
    assert is_informational_question(
        _SETTLEMENT_TIMING_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY,
    )


def test_policy_question_no_followup_required() -> None:
    text = "آیا فروش این کالا مجاز است؟"
    assert is_informational_question(
        text,
        detected_intent=VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
    )
    assert not draft_requires_operational_followup(
        seller_text=text,
        suggested_action="answer_policy_question",
        detected_intent=VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
    )


def test_operational_review_ticket_requires_followup() -> None:
    text = "لطفاً وضعیت سفارش 1234567 را بررسی کنید"
    assert draft_requires_operational_followup(
        seller_text=text,
        suggested_action="check_order_status",
        detected_intent=VendorTicketIntent.ORDER_STATUS_REVIEW,
    )
    draft = "برای بررسی به تیم مربوطه ارجاع شد."
    assert not detect_unnecessary_followup_in_draft(
        draft,
        seller_text=text,
        suggested_action="check_order_status",
        detected_intent=VendorTicketIntent.ORDER_STATUS_REVIEW,
    )


def test_escalation_ticket_allows_followup() -> None:
    text = "شکایت جدی دارم"
    assert draft_requires_operational_followup(
        seller_text=text,
        suggested_action="escalate",
        detected_intent=VendorTicketIntent.COMPLAINT_ESCALATION,
    )
    draft = "مورد در حال بررسی است. نتیجه اطلاع‌رسانی خواهد شد."
    assert not detect_unnecessary_followup_in_draft(
        draft,
        seller_text=text,
        suggested_action="escalate",
        detected_intent=VendorTicketIntent.COMPLAINT_ESCALATION,
    )


def test_detect_filler_sentence_patterns() -> None:
    assert detect_unnecessary_followup_sentence("لطفا کمی صبر کنید تا بررسی لازم انجام شود.")
    assert detect_unnecessary_followup_sentence("مورد در حال بررسی است.")
    assert not detect_unnecessary_followup_sentence(_SETTLEMENT_DRAFT_CLEAN)


def test_strip_trailing_filler_settlement_example() -> None:
    cleaned, removed = strip_unnecessary_trailing_followup(
        _SETTLEMENT_DRAFT_WITH_FILLER,
        seller_text=_SETTLEMENT_TIMING_QUESTION,
        suggested_action="check_settlement_status",
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY,
    )
    assert removed is True
    assert cleaned == _SETTLEMENT_DRAFT_CLEAN
    assert "صبر کنید" not in cleaned


def test_apply_calibration_leaves_operational_draft_unchanged() -> None:
    seller = "لطفاً سفارش 1234567 را پیگیری کنید"
    draft = "برای بررسی به تیم مربوطه ارجاع شد."
    result = apply_draft_completion_calibration(
        draft,
        seller_text=seller,
        suggested_action="human_followup",
        detected_intent=VendorTicketIntent.SELLER_OPERATIONAL_REQUEST,
    )
    assert result.draft_reply == draft
    assert result.completion_calibration_applied is False


def test_prompt_includes_completion_instruction() -> None:
    block = merge_style_and_completion_instructions("operational_short")
    assert "پاسخ را همان‌جا تمام کن" in block
    assert "جمله پیگیری یا انتظار اضافه نکن" in block
    assert build_completion_calibration_instruction() in block
