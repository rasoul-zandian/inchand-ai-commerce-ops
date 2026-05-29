"""Tests for advisory suggested-action taxonomy v1 (Step 180)."""

from __future__ import annotations

from app.workflows.suggested_action_taxonomy import (
    is_operational_request,
    map_intent_to_suggested_action,
    monitor_fallback_allowed,
    should_suppress_monitor,
)
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistActionType
from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow
from app.workflows.vendor_ticket_intent_detection import (
    VendorTicketIntent,
    VendorTicketIntentDetectionResult,
)


def _intent_result(**kwargs: object) -> VendorTicketIntentDetectionResult:
    defaults: dict[str, object] = {
        "detected_intent": VendorTicketIntent.UNKNOWN.value,
        "confidence_band": "medium",
        "reasons": [],
        "extracted_order_ids": [],
        "extracted_product_ids": [],
        "extracted_tracking_code": None,
        "extracted_tracking_carrier": None,
        "entity_warnings_summary": None,
        "related_document_types": [],
    }
    defaults.update(kwargs)
    return VendorTicketIntentDetectionResult(**defaults)  # type: ignore[arg-type]


def test_delivery_confirmation_maps_to_update_delivery_status() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST,
        normalized_text="تحویل را ثبت کنید",
        conceptual_intent_fa="ثبت تحویل سفارش",
    )
    assert mapping.action == VendorTicketAIAssistActionType.UPDATE_DELIVERY_STATUS


def test_product_approval_maps_to_check_product_approval() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.PRODUCT_APPROVAL_REVIEW,
        normalized_text="کالا تایید نشده",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_PRODUCT_APPROVAL


def test_product_edit_maps_to_review_product_edit() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="لطفاً ویرایش کالا و تغییر نام کالا را بررسی کنید",
    )
    assert mapping.action == VendorTicketAIAssistActionType.REVIEW_PRODUCT_EDIT


def test_return_refund_maps_to_check_return_request() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="درخواست بازگشت کالا و استرداد وجه",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_RETURN_REQUEST


def test_settlement_inquiry_maps_to_check_settlement_status() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY,
        normalized_text="تسویه من واریز نشده",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_SETTLEMENT_STATUS


def test_commission_policy_maps_to_policy_explanation_action() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.COMMISSION_POLICY_QUESTION,
        normalized_text="کمیسیون فروش چند درصده؟",
    )
    assert mapping.action == VendorTicketAIAssistActionType.ANSWER_POLICY_QUESTION


def test_passive_notification_maps_to_monitor_or_record() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="سلام وقت بخیر",
    )
    assert mapping.action == VendorTicketAIAssistActionType.MONITOR


def test_ask_verbs_unknown_intent_maps_to_human_followup() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.UNKNOWN,
        normalized_text="لطفاً وضعیت را بررسی کنید",
    )
    assert mapping.action == VendorTicketAIAssistActionType.HUMAN_FOLLOWUP


def test_entity_warnings_map_to_request_missing_info() -> None:
    entities = _intent_result(entity_warnings_summary="شناسه محصول ناقص احتمالی")
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        entities=entities,
        normalized_text="سلام وقت بخیر",
    )
    assert mapping.action == VendorTicketAIAssistActionType.REQUEST_MISSING_INFO


def test_entity_warnings_refined_when_order_followup_clear() -> None:
    entities = _intent_result(entity_warnings_summary="شماره سفارش ناقص احتمالی")
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.ORDER_STATUS_REVIEW,
        entities=entities,
        normalized_text="پیگیری سفارش 123456",
        conceptual_intent_fa="پیگیری وضعیت سفارش",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_ORDER_STATUS
    assert mapping.fallback_reason == "missing_info_refined_order"


def test_operational_conceptual_cannot_fallback_to_monitor() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="لطفاً ثبت تحویل سفارش را انجام دهید",
        conceptual_intent_fa="ثبت تحویل سفارش",
    )
    assert mapping.action != VendorTicketAIAssistActionType.MONITOR
    assert mapping.monitor_blocked_by_operational_signals is True


def test_remove_complaint_maps_to_human_followup() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="مشکل حل شد لطفا شکایت رو بردارید",
    )
    assert mapping.action == VendorTicketAIAssistActionType.HUMAN_FOLLOWUP
    assert mapping.fallback_reason == "complaint_resolution"


def test_settlement_panel_operational_maps_to_check_settlement() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE,
        normalized_text="پنل تسویه بسته است و واریز نشده",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_SETTLEMENT_STATUS


def test_cancellation_request_maps_to_human_followup() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.CANCELLATION_REQUEST,
        normalized_text="سفارش 7367917 لغو شود",
    )
    assert mapping.action == VendorTicketAIAssistActionType.HUMAN_FOLLOWUP
    assert mapping.fallback_reason == "cancellation_request"


def test_cancellation_overrides_seller_notification_action() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SELLER_NOTIFICATION,
        normalized_text="سفارش 7367917 لغو شود",
    )
    assert mapping.action == VendorTicketAIAssistActionType.HUMAN_FOLLOWUP
    assert mapping.fallback_reason == "cancellation_request"


def test_tracking_notification_only_maps_to_record_update() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.TRACKING_CODE_NOTIFICATION,
        normalized_text="کد رهگیری 123456789012345678901234 ارسال شد",
    )
    assert mapping.action == VendorTicketAIAssistActionType.RECORD_UPDATE


def test_unclear_passive_text_allows_monitor() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.UNKNOWN,
        normalized_text="سلام وقت بخیر",
    )
    assert mapping.action == VendorTicketAIAssistActionType.MONITOR
    assert mapping.fallback_reason == "passive_greeting"
    assert is_operational_request(normalized_text="سلام وقت بخیر") is False
    assert monitor_fallback_allowed(normalized_text="سلام وقت بخیر", detected_intent="unknown")


def test_delivery_with_order_id_prefers_update_delivery() -> None:
    entities = _intent_result(
        detected_intent=VendorTicketIntent.GENERAL_VENDOR_SUPPORT.value,
        extracted_order_ids=["1234567"],
    )
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        entities=entities,
        normalized_text="ثبت تحویل سفارش 1234567",
        conceptual_intent_fa="ثبت تحویل",
    )
    assert mapping.action == VendorTicketAIAssistActionType.UPDATE_DELIVERY_STATUS


def test_general_support_product_approval_conceptual_not_monitor() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="کالا هنوز فعال نشده",
        conceptual_intent_fa="درخواست تایید کالا",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_PRODUCT_APPROVAL
    assert mapping.action != VendorTicketAIAssistActionType.MONITOR


def test_return_followup_conceptual_maps_to_check_return() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SELLER_NOTIFICATION,
        normalized_text="وضعیت مرجوعی را بفرمایید",
        conceptual_intent_fa="پیگیری مرجوعی سفارش",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_RETURN_REQUEST


def test_complaint_close_maps_to_human_followup_not_escalate() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="مشکل برطرف شد",
        conceptual_intent_fa="درخواست بستن شکایت",
    )
    assert mapping.action == VendorTicketAIAssistActionType.HUMAN_FOLLOWUP
    assert mapping.action != VendorTicketAIAssistActionType.ESCALATE


def test_order_followup_with_order_id_maps_to_check_order_status() -> None:
    entities = _intent_result(extracted_order_ids=["7654321"])
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        entities=entities,
        normalized_text="سفارش 7654321",
        conceptual_intent_fa="پیگیری سفارش",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_ORDER_STATUS


def test_greeting_only_stays_monitor() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="سلام وقت بخیر",
    )
    assert mapping.action == VendorTicketAIAssistActionType.MONITOR
    suppress = should_suppress_monitor(
        detected_intent=VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="سلام وقت بخیر",
    )
    assert suppress.suppress is False


def test_vague_passive_notification_stays_monitor() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SELLER_NOTIFICATION,
        normalized_text="اطلاع می‌دهم که پیام دریافت شد",
    )
    assert mapping.action == VendorTicketAIAssistActionType.MONITOR
    assert mapping.fallback_reason == "passive_notification"


def test_missing_info_refined_to_return_when_conceptual_clear() -> None:
    entities = _intent_result(entity_warnings_summary="شناسه سفارش نامشخص")
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.SELLER_NOTIFICATION,
        entities=entities,
        normalized_text="مرجوعی سفارش",
        conceptual_intent_fa="پیگیری مرجوعی سفارش",
    )
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_RETURN_REQUEST
    assert mapping.fallback_reason == "missing_info_refined_return"


def test_complaint_close_without_escalation_language_not_escalate() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.GENERAL_VENDOR_SUPPORT,
        normalized_text="لطفاً شکایت را ببندید",
        conceptual_intent_fa="درخواست بستن شکایت",
    )
    assert mapping.action != VendorTicketAIAssistActionType.ESCALATE


def test_monitor_suppressed_metadata_on_operational_conceptual() -> None:
    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.UNKNOWN,
        normalized_text="",
        conceptual_intent_fa="درخواست تایید کالا",
    )
    assert mapping.monitor_suppressed or mapping.monitor_blocked_by_operational_signals
    assert mapping.action == VendorTicketAIAssistActionType.CHECK_PRODUCT_APPROVAL


def test_shadow_assist_includes_action_reason() -> None:
    result = evaluate_vendor_ticket_ai_assist_shadow(
        {
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "review_priority": "LOW",
            "retrieval_gate_decision": "allow",
            "retrieval_result_count": 1,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "latest_vendor_message": "تحویل‌شون رو ثبت کنید — سفارش 1234567",
        },
    )
    assert result.suggested_action == VendorTicketAIAssistActionType.UPDATE_DELIVERY_STATUS
    assert result.suggested_action_reason
