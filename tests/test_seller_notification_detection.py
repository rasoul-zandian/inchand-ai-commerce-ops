"""Tests for seller notification vs operational-request detection."""

from __future__ import annotations

from app.operator_console.console_models import OperatorTicket
from app.workflows.seller_notification_detection import (
    SellerIntentType,
    detect_seller_notification,
    extract_order_ids,
    normalize_persian_arabic_digits,
)
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistActionType
from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow

_IRAN_POST_TRACKING = "4" * 24


def test_detects_shipment_notification_with_order_and_tracking() -> None:
    text = f"سفارش شماره 2322222 ارسال شد و کد رهگیری {_IRAN_POST_TRACKING} می‌باشد"
    result = detect_seller_notification(text)
    assert result.seller_intent == SellerIntentType.SELLER_NOTIFICATION.value
    assert result.is_seller_notification is True
    assert result.entities.order_id == "2322222"
    assert result.entities.tracking_code == _IRAN_POST_TRACKING
    assert result.notification_type == "tracking_code_update"
    assert result.confidence_band == "high"


def test_tracking_code_synonyms() -> None:
    for phrase in (
        f"کد پیگیری {'9' * 24}",
        f"بارکد پستی {'1' * 24}",
    ):
        result = detect_seller_notification(phrase)
        assert result.is_seller_notification is True
        assert result.entities.tracking_code is not None


def test_normalizes_persian_digits_and_extracts_multiple_order_ids() -> None:
    text = "سفارش‌های ۱۲۳۴۵۶۷ و ۴۵۶۷۸۹۰ را بررسی کنید"
    ids = extract_order_ids(normalize_persian_arabic_digits(text))
    assert ids == ("1234567", "4567890")
    result = detect_seller_notification(text)
    assert result.is_seller_operational_request is True
    assert result.entities.order_ids == ("1234567", "4567890")


def test_order_list_after_label() -> None:
    ids = extract_order_ids("شماره سفارش: 7890123, 1011123")
    assert ids == ("7890123", "1011123")


def test_non_seller_message_returns_undetected() -> None:
    result = detect_seller_notification("سلام، وقتتون بخیر")
    assert result.is_detected is False
    assert result.seller_intent is None


def test_cancellation_not_classified_as_seller_notification() -> None:
    result = detect_seller_notification("سفارش 7367917 لغو شود")
    assert result.is_detected is False
    assert result.seller_intent is None
    assert "cancellation_request_preempts_notification" in result.reasons


def test_operational_request_order_status_review() -> None:
    result = detect_seller_notification("لطفاً وضعیت سفارش 1234567 را بررسی کنید")
    assert result.is_seller_operational_request is True
    assert result.operational_request_type == "order_status_review"
    assert result.entities.order_id == "1234567"
    assert result.is_seller_notification is False


def test_ai_assist_maps_notification_to_record_update() -> None:
    tracking = "9" * 24
    result = evaluate_vendor_ticket_ai_assist_shadow(
        {
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "review_priority": "LOW",
            "retrieval_gate_decision": "allow",
            "retrieval_result_count": 1,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "latest_vendor_message": (f"سفارش شماره 1234567 ارسال شد و کد رهگیری {tracking}"),
        },
    )
    assert result.seller_intent_type == "seller_notification"
    assert result.seller_notification_detected is True
    assert result.suggested_action == VendorTicketAIAssistActionType.RECORD_UPDATE
    assert result.detected_intent == "tracking_code_notification"
    assert result.escalation_recommended is False
    assert result.extracted_order_id == "1234567"
    assert result.extracted_tracking_code == tracking


def test_ai_assist_maps_operational_to_human_followup() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        {
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "review_priority": "LOW",
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "latest_vendor_message": "وضعیت سفارش 9990000 را پیگیری کنید",
        },
    )
    assert result.seller_intent_type == "seller_operational_request"
    assert result.suggested_action == VendorTicketAIAssistActionType.CHECK_ORDER_STATUS
    assert result.escalation_recommended is False
    assert result.human_review_required is True


def test_ai_assist_product_approval_uses_check_product_approval() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        {
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "latest_vendor_message": "لطفاً انتشار کالا را بررسی کنید",
        },
    )
    assert result.suggested_action == VendorTicketAIAssistActionType.CHECK_PRODUCT_APPROVAL
    assert result.seller_operational_request_type == "product_approval_review"


def test_console_model_displays_seller_intent_fields() -> None:
    ticket = OperatorTicket.from_hitl_payload(
        {
            "room_id": "ROOM_SN",
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "ai_assist_shadow_generated": True,
            "ai_assist_suggested_action": "human_followup",
            "ai_assist_suggested_priority": "medium",
            "ai_assist_escalation_recommended": False,
            "ai_assist_duplicate_possible": False,
            "ai_assist_confidence_band": "medium",
            "ai_assist_human_review_required": True,
            "ai_assist_shadow_only": True,
            "seller_intent_type": "seller_operational_request",
            "seller_operational_request_type": "order_status_review",
            "extracted_order_ids": "1234567,4567890",
            "extracted_order_id": "1234567",
        },
    )
    assert ticket.seller_intent_type == "seller_operational_request"
    assert ticket.extracted_order_ids == "1234567,4567890"
