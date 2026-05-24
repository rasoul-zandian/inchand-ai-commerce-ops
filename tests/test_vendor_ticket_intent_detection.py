"""Tests for rule-based vendor ticket operational intent taxonomy v1."""

from __future__ import annotations

from app.operator_console.console_models import OperatorTicket
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistActionType
from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow
from app.workflows.vendor_ticket_intent_detection import (
    VendorTicketIntent,
    detect_vendor_ticket_intent,
)


def test_settlement_panel_access_issue() -> None:
    result = detect_vendor_ticket_intent("تصفیه پنل برای من بسته است")
    assert result.detected_intent == VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value
    assert result.confidence_band in ("medium", "high")
    assert "settlement_rules" in result.related_document_types


def test_settlement_status_inquiry() -> None:
    result = detect_vendor_ticket_intent("تسویه من واریز نشده است")
    assert result.detected_intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value
    assert any("keyword:" in r for r in result.reasons)


def test_product_approval_review() -> None:
    result = detect_vendor_ticket_intent("کالا تایید نشده، چرا تایید نشد؟")
    assert result.detected_intent == VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value


def test_product_publishing_question() -> None:
    result = detect_vendor_ticket_intent("نام کالا و عکس کالا را چطور ثبت کنم؟")
    assert result.detected_intent == VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value


def test_prohibited_goods_question() -> None:
    result = detect_vendor_ticket_intent("آیا فروش دخانیات غیرمجاز است؟")
    assert result.detected_intent == VendorTicketIntent.PROHIBITED_GOODS_QUESTION.value


def test_delivery_confirmation_with_multiple_order_ids() -> None:
    text = "تحویل‌شون رو ثبت کنید — سفارش‌های ۱۲۳۴۵۶۷ و ۴۵۶۷۸۹۰"
    result = detect_vendor_ticket_intent(text)
    assert result.detected_intent == VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value
    assert result.extracted_order_ids == ["1234567", "4567890"]


def test_tracking_code_notification() -> None:
    tracking = "1" * 24
    result = detect_vendor_ticket_intent(
        f"سفارش 1234567 ارسال شد، کد رهگیری {tracking}",
    )
    assert result.detected_intent == VendorTicketIntent.TRACKING_CODE_NOTIFICATION.value
    assert result.extracted_tracking_code == tracking
    assert result.extracted_tracking_carrier == "iran_post"


def test_complaint_escalation() -> None:
    result = detect_vendor_ticket_intent("می‌خواهم شکایت رسمی ثبت کنم")
    assert result.detected_intent == VendorTicketIntent.COMPLAINT_ESCALATION.value


def test_unknown_fallback_without_signals() -> None:
    result = detect_vendor_ticket_intent("سلام وقت بخیر")
    assert result.detected_intent == VendorTicketIntent.UNKNOWN.value


def test_ai_assist_includes_detected_intent() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        {
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "latest_vendor_message": "تسویه من واریز نشده",
        },
    )
    assert result.detected_intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value
    assert result.intent_confidence_band in ("low", "medium", "high")
    assert result.intent_reasons_summary
    assert result.intent_related_document_types
    assert result.suggested_action == VendorTicketAIAssistActionType.CHECK_SETTLEMENT_STATUS


def test_operator_model_carries_intent_fields() -> None:
    ticket = OperatorTicket.from_hitl_payload(
        {
            "room_id": "ROOM_INTENT",
            "ticket_label": "fund",
            "detected_intent": "settlement_status_inquiry",
            "intent_confidence_band": "medium",
            "intent_reasons_summary": "keyword:تسویه",
            "intent_related_document_types": "settlement_rules,vendor_general_policy",
            "extracted_order_ids": "1001",
        },
    )
    assert ticket.detected_intent == "settlement_status_inquiry"
    assert ticket.intent_confidence_band == "medium"
    assert ticket.intent_reasons_summary == "keyword:تسویه"
    assert ticket.intent_related_document_types == "settlement_rules,vendor_general_policy"
