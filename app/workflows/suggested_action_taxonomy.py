"""Advisory suggested-action taxonomy v1 (HITL/shadow only — no execution)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.workflows.cancellation_request_detection import is_cancellation_request_message
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistActionType
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

SuggestedAction = VendorTicketAIAssistActionType

_OPERATIONAL_ASK_MARKERS = (
    "ثبت کنید",
    "ثبت کن",
    "بررسی کنید",
    "چک کنید",
    "پیگیری کنید",
    "تایید کنید",
    "تأیید کنید",
    "اصلاح کنید",
    "ویرایش کنید",
    "لغو کنید",
    "باز کنید",
    "لطفا بررسی",
    "لطفاً بررسی",
    "لطفا چک",
    "لطفاً چک",
    "لطفا پیگیری",
    "لطفاً پیگیری",
    "اعلام کنید",
    "مشکل از چیه",
    "مشکل از چیست",
)

_MONITOR_SUPPRESSION_CONCEPTUAL_STEMS = (
    "ثبت",
    "تغییر",
    "تایید",
    "تأیید",
    "ویرایش",
    "مرجوع",
    "پیگیری",
    "شکایت",
    "بررسی",
)

_OPERATIONAL_CONCEPTUAL_MARKERS = (
    "ثبت تحویل",
    "پیگیری سفارش",
    "وضعیت سفارش",
    "پیگیری وضعیت سفارش",
    "تایید کالا",
    "تأیید کالا",
    "عدم تایید",
    "درخواست تایید کالا",
    "درخواست فعال‌سازی",
    "فعال‌سازی کالا",
    "ویرایش کالا",
    "تغییر نام کالا",
    "اصلاح کالا",
    "بازگشت کالا",
    "مرجوعی",
    "پیگیری مرجوعی",
    "استرداد",
)

_DELIVERY_CONCEPTUAL_MARKERS = ("ثبت تحویل", "ثبت تحویل سفارش")
_ORDER_STATUS_CONCEPTUAL_MARKERS = (
    "پیگیری سفارش",
    "وضعیت سفارش",
    "پیگیری وضعیت سفارش",
)
_PRODUCT_APPROVAL_CONCEPTUAL_MARKERS = (
    "تایید کالا",
    "تأیید کالا",
    "عدم تایید",
    "درخواست تایید کالا",
)
_PRODUCT_EDIT_MARKERS = (
    "ویرایش کالا",
    "تغییر نام کالا",
    "تغییر عکس",
    "اصلاح کالا",
    "اصلاح مشخصات کالا",
    "تغییر مشخصات",
)
_RETURN_REFUND_MARKERS = (
    "بازگشت کالا",
    "مرجوعی",
    "پیگیری مرجوعی",
    "استرداد",
    "عودت کالا",
    "بازگشت وجه",
    "refund",
    "return request",
)

_TRACKING_UPDATE_MARKERS = (
    "پیگیری وضعیت پست",
    "وضعیت پست",
    "کد رهگیری",
    "رهگیری",
)

_COMPLAINT_CLOSE_MARKERS = (
    "بستن شکایت",
    "درخواست بستن شکایت",
    "بستن شکایت فروشنده",
)

_COMPLAINT_ESCALATION_MARKERS = (
    "شکایت جدی",
    "تخلف",
    "نارضایتی شدید",
    "پیگیری فوری شکایت",
)

_COMPLAINT_RESOLUTION_MARKERS = (
    "شکایت رو بردارید",
    "شکایت را بردارید",
    "لطفا شکایت رو بردارید",
    "لطفاً شکایت رو بردارید",
    "بردارید شکایت",
    "حذف شکایت",
    "لغو شکایت",
    "برداشتن شکایت",
)

_SETTLEMENT_OPERATIONAL_MARKERS = (
    "پنل بسته",
    "پنل تسویه",
    "واریز نشده",
    "تسویه نشده",
    "پرداخت نشده",
    "کیف پول",
    "برداشت",
)

_PASSIVE_GREETING_MARKERS = (
    "سلام",
    "وقت بخیر",
    "درود",
    "خسته نباشید",
    "ممنون",
    "متشکر",
)

_POLICY_ONLY_MARKERS = (
    "مجاز است",
    "مجاز هست",
    "قوانین",
    "مقررات",
    "سیاست",
    "چند روز",
    "چه زمانی",
    "آیا می",
    "کمیسیون",
    "کارمزد",
    "هزینه فروش",
    "درصد",
)

_INTENTS_WITH_SPECIFIC_ACTION = frozenset(
    {
        VendorTicketIntent.COMPLAINT_ESCALATION,
        VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST,
        VendorTicketIntent.TRACKING_CODE_NOTIFICATION,
        VendorTicketIntent.ORDER_STATUS_REVIEW,
        VendorTicketIntent.PRODUCT_APPROVAL_REVIEW,
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION,
        VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE,
        VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY,
        VendorTicketIntent.SELLER_NOTIFICATION,
        VendorTicketIntent.SELLER_OPERATIONAL_REQUEST,
        VendorTicketIntent.CANCELLATION_REQUEST,
    },
)


class _EntityFields(Protocol):
    extracted_order_ids: list[str]
    extracted_product_ids: list[str]
    extracted_tracking_code: str | None
    entity_warnings_summary: str | None


@dataclass(frozen=True)
class MonitorSuppressionResult:
    """Whether passive ``monitor`` must be replaced with a specific action."""

    suppress: bool
    reason: str


@dataclass(frozen=True)
class SuggestedActionMapping:
    """Primary suggested operator action plus short advisory reason."""

    action: VendorTicketAIAssistActionType
    reason: str
    monitor_blocked_by_operational_signals: bool = False
    monitor_suppressed: bool = False
    monitor_suppression_reason: str | None = None
    fallback_reason: str | None = None


def _resolve_intent(detected_intent: str | VendorTicketIntent) -> VendorTicketIntent:
    if isinstance(detected_intent, VendorTicketIntent):
        return detected_intent
    try:
        return VendorTicketIntent(str(detected_intent).strip().lower())
    except ValueError:
        return VendorTicketIntent.UNKNOWN


def _conceptual_blob(conceptual_intent_fa: str | None, normalized_text: str) -> str:
    parts = [normalized_text.strip()]
    if conceptual_intent_fa:
        parts.append(conceptual_intent_fa.strip())
    return " ".join(p for p in parts if p)


def _has_any(blob: str, markers: tuple[str, ...]) -> bool:
    return any(marker in blob for marker in markers)


def _seller_asks_operational_action(blob: str) -> bool:
    return _has_any(blob, _OPERATIONAL_ASK_MARKERS)


def _has_operational_conceptual_intent(blob: str) -> bool:
    if _has_any(blob, _OPERATIONAL_CONCEPTUAL_MARKERS):
        return True
    return _conceptual_stem_suppresses_monitor(blob)


def _conceptual_stem_suppresses_monitor(blob: str) -> bool:
    return any(stem in blob for stem in _MONITOR_SUPPRESSION_CONCEPTUAL_STEMS)


def _general_support_with_operational_conceptual(
    intent: VendorTicketIntent,
    blob: str,
) -> bool:
    return (
        intent == VendorTicketIntent.GENERAL_VENDOR_SUPPORT
        and _has_operational_conceptual_intent(
            blob,
        )
    )


def _entities_with_ask_verb(blob: str, entities: _EntityFields | Any | None) -> bool:
    return _has_extracted_entities(entities) and _seller_asks_operational_action(blob)


def _has_extracted_entities(entities: _EntityFields | Any | None) -> bool:
    if entities is None:
        return False
    order_ids = getattr(entities, "extracted_order_ids", None) or []
    product_ids = getattr(entities, "extracted_product_ids", None) or []
    tracking = getattr(entities, "extracted_tracking_code", None)
    if order_ids:
        return True
    if product_ids:
        return True
    return bool(tracking and str(tracking).strip())


def _entity_warnings(entities: _EntityFields | None) -> str | None:
    if entities is None:
        return None
    raw = getattr(entities, "entity_warnings_summary", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def is_operational_request(
    *,
    normalized_text: str = "",
    conceptual_intent_fa: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entities: _EntityFields | Any | None = None,
    seller_intent_type: str | None = None,
    seller_operational_request_type: str | None = None,
) -> bool:
    """True when seller text/signals imply support should act (not passive monitor)."""
    blob = _conceptual_blob(conceptual_intent_fa, normalized_text)
    intent = _resolve_intent(detected_intent) if detected_intent is not None else None

    if seller_intent_type == VendorTicketIntent.SELLER_OPERATIONAL_REQUEST.value:
        return True
    if seller_intent_type == "seller_operational_request":
        return True
    if (
        seller_operational_request_type
        and seller_operational_request_type != "general_support_request"
    ):
        return True
    if is_cancellation_request_message(blob):
        return True
    if intent == VendorTicketIntent.CANCELLATION_REQUEST:
        return True
    if intent == VendorTicketIntent.SELLER_OPERATIONAL_REQUEST:
        return True
    if _seller_asks_operational_action(blob):
        return True
    if _has_operational_conceptual_intent(blob):
        return True
    if _entities_with_ask_verb(blob, entities):
        return True
    if _has_extracted_entities(entities) and _has_operational_conceptual_intent(blob):
        return True
    if intent == VendorTicketIntent.GENERAL_VENDOR_SUPPORT and _has_operational_conceptual_intent(
        blob,
    ):
        return True
    if intent in _INTENTS_WITH_SPECIFIC_ACTION and intent not in (
        VendorTicketIntent.SELLER_NOTIFICATION,
        VendorTicketIntent.TRACKING_CODE_NOTIFICATION,
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION,
        VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY,
        VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE,
    ):
        return True
    if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS):
        return True
    return False


def action_requires_specific_followup(
    detected_intent: str | VendorTicketIntent,
) -> bool:
    """True when taxonomy maps this intent to a non-monitor advisory action."""
    intent = _resolve_intent(detected_intent)
    return intent in _INTENTS_WITH_SPECIFIC_ACTION


def _is_passive_greeting_or_noop(blob: str) -> bool:
    text = blob.strip()
    if not text:
        return True
    if len(text) > 120:
        return False
    if not _has_any(text, _PASSIVE_GREETING_MARKERS):
        return False
    if _seller_asks_operational_action(text):
        return False
    if _has_operational_conceptual_intent(text):
        return False
    if _has_any(text, _OPERATIONAL_ASK_MARKERS):
        return False
    return True


def _is_tracking_notification_only(
    intent: VendorTicketIntent,
    blob: str,
    *,
    entities: _EntityFields | Any | None,
) -> bool:
    if is_cancellation_request_message(blob):
        return False
    if intent == VendorTicketIntent.CANCELLATION_REQUEST:
        return False
    if intent == VendorTicketIntent.TRACKING_CODE_NOTIFICATION:
        return True
    if intent == VendorTicketIntent.SELLER_NOTIFICATION:
        if _first_tracking_only(blob, entities) and not _seller_asks_operational_action(blob):
            return True
    return False


def _first_tracking_only(blob: str, entities: _EntityFields | Any | None) -> bool:
    tracking = getattr(entities, "extracted_tracking_code", None) if entities else None
    has_tracking = (
        bool(tracking and str(tracking).strip()) or "کد رهگیری" in blob or "رهگیری" in blob
    )
    has_orders = bool(getattr(entities, "extracted_order_ids", None) if entities else None)
    return has_tracking and not _seller_asks_operational_action(blob) and not has_orders


def _is_policy_question_only(intent: VendorTicketIntent, blob: str) -> bool:
    if intent in (
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION,
        VendorTicketIntent.COMMISSION_POLICY_QUESTION,
    ):
        return True
    if "؟" in blob or "?" in blob:
        if _has_any(blob, _POLICY_ONLY_MARKERS) and not _seller_asks_operational_action(blob):
            return True
    return False


def should_suppress_monitor(
    *,
    detected_intent: str | VendorTicketIntent | None = None,
    conceptual_intent_fa: str | None = None,
    normalized_text: str = "",
    entities: _EntityFields | Any | None = None,
    seller_intent_type: str | None = None,
    seller_operational_request_type: str | None = None,
    ticket_label: str | None = None,
    route_label: str | None = None,
) -> MonitorSuppressionResult:
    """True when ``monitor`` would be wrong — a concrete advisory action is required."""
    intent = (
        _resolve_intent(detected_intent)
        if detected_intent is not None
        else VendorTicketIntent.UNKNOWN
    )
    blob = _conceptual_blob(conceptual_intent_fa, normalized_text)

    if is_operational_request(
        normalized_text=normalized_text,
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=intent,
        entities=entities,
        seller_intent_type=seller_intent_type,
        seller_operational_request_type=seller_operational_request_type,
    ):
        return MonitorSuppressionResult(True, "operational_request_signals")

    if _conceptual_stem_suppresses_monitor(blob):
        return MonitorSuppressionResult(True, "conceptual_operational_stem")

    if _general_support_with_operational_conceptual(intent, blob):
        return MonitorSuppressionResult(True, "general_support_operational_conceptual")

    if seller_intent_type in (
        VendorTicketIntent.SELLER_OPERATIONAL_REQUEST.value,
        "seller_operational_request",
    ):
        return MonitorSuppressionResult(True, "seller_operational_request")

    if (
        seller_operational_request_type
        and seller_operational_request_type != "general_support_request"
    ):
        return MonitorSuppressionResult(True, "seller_operational_request_type")

    if _entities_with_ask_verb(blob, entities):
        return MonitorSuppressionResult(True, "entities_with_ask_verb")

    if _has_any(blob, _COMPLAINT_RESOLUTION_MARKERS) or _has_any(blob, _COMPLAINT_CLOSE_MARKERS):
        return MonitorSuppressionResult(True, "complaint_resolution_or_close")

    if intent == VendorTicketIntent.COMPLAINT_ESCALATION:
        return MonitorSuppressionResult(True, "complaint_escalation_intent")

    if action_requires_specific_followup(intent) and intent not in (
        VendorTicketIntent.SELLER_NOTIFICATION,
        VendorTicketIntent.TRACKING_CODE_NOTIFICATION,
    ):
        return MonitorSuppressionResult(True, f"specific_intent:{intent.value}")

    _ = ticket_label, route_label
    return MonitorSuppressionResult(False, "")


def _complaint_requires_escalation(blob: str, intent: VendorTicketIntent) -> bool:
    if intent == VendorTicketIntent.COMPLAINT_ESCALATION:
        return True
    return _has_any(blob, _COMPLAINT_ESCALATION_MARKERS)


def _map_suppressed_monitor_action(
    intent: VendorTicketIntent,
    blob: str,
    *,
    entities: _EntityFields | Any | None,
    seller_operational_request_type: str | None,
    suppression_reason: str,
) -> SuggestedActionMapping:
    """Pick a specific advisory action when monitor is suppressed (Step 188)."""
    specific = _resolve_operational_specific_action(
        intent,
        blob,
        entities=entities,
        seller_operational_request_type=seller_operational_request_type,
    )
    if specific is not None:
        return SuggestedActionMapping(
            action=specific.action,
            reason=specific.reason,
            monitor_blocked_by_operational_signals=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason=specific.fallback_reason or "monitor_suppressed_specific",
        )

    if _has_any(blob, _COMPLAINT_RESOLUTION_MARKERS) or _has_any(blob, _COMPLAINT_CLOSE_MARKERS):
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "complaint close/resolution — human follow-up (not escalate)",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="complaint_close_human_followup",
        )

    if _has_any(blob, _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_PRODUCT_APPROVAL,
            "product approval conceptual intent suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="product_approval",
        )

    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        return _mapping(
            SuggestedAction.REVIEW_PRODUCT_EDIT,
            "product edit conceptual intent suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="product_edit",
        )

    if _has_any(blob, _RETURN_REFUND_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_RETURN_REQUEST,
            "return/refund conceptual intent suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="return_refund",
        )

    if _has_any(blob, _ORDER_STATUS_CONCEPTUAL_MARKERS) or (
        _has_extracted_entities(entities)
        and bool(getattr(entities, "extracted_order_ids", None) or [])
    ):
        return _mapping(
            SuggestedAction.CHECK_ORDER_STATUS,
            "order follow-up conceptual intent suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="order_status",
        )

    if _has_any(blob, _DELIVERY_CONCEPTUAL_MARKERS):
        return _mapping(
            SuggestedAction.UPDATE_DELIVERY_STATUS,
            "delivery confirmation suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="delivery_confirmation",
        )

    if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_SETTLEMENT_STATUS,
            "settlement operational language suppresses monitor",
            operational_context=True,
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="settlement_operational",
        )

    if _has_any(blob, _TRACKING_UPDATE_MARKERS):
        return _mapping(
            SuggestedAction.RECORD_UPDATE,
            "tracking/post update language suppresses monitor",
            monitor_suppressed=True,
            monitor_suppression_reason=suppression_reason,
            fallback_reason="tracking_update",
        )

    return _mapping(
        SuggestedAction.HUMAN_FOLLOWUP,
        "monitor suppressed — default human follow-up",
        operational_context=True,
        monitor_suppressed=True,
        monitor_suppression_reason=suppression_reason,
        fallback_reason="monitor_suppressed_default",
    )


def _refine_request_missing_info_action(
    intent: VendorTicketIntent,
    blob: str,
    *,
    entities: _EntityFields | Any | None,
    warnings: str,
    seller_operational_request_type: str | None,
) -> SuggestedActionMapping | None:
    """Prefer operational action over request_missing_info when conceptual intent is clear."""
    from app.workflows.operational_information_sufficiency import is_seller_panel_issue

    if is_seller_panel_issue(blob, detected_intent=intent.value):
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "panel issue — shop_id in metadata; nazer review",
            operational_context=True,
            fallback_reason="panel_issue_human_followup",
        )
    if _has_any(blob, _RETURN_REFUND_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_RETURN_REQUEST,
            f"return/refund language overrides missing-info ({warnings[:40]})",
            operational_context=True,
            fallback_reason="missing_info_refined_return",
        )
    if _has_any(blob, _ORDER_STATUS_CONCEPTUAL_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_ORDER_STATUS,
            f"order follow-up overrides missing-info ({warnings[:40]})",
            operational_context=True,
            fallback_reason="missing_info_refined_order",
        )
    if _has_any(blob, _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_PRODUCT_APPROVAL,
            f"product approval overrides missing-info ({warnings[:40]})",
            operational_context=True,
            fallback_reason="missing_info_refined_product_approval",
        )
    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        return _mapping(
            SuggestedAction.REVIEW_PRODUCT_EDIT,
            f"product edit overrides missing-info ({warnings[:40]})",
            operational_context=True,
            fallback_reason="missing_info_refined_product_edit",
        )
    refined = _resolve_operational_specific_action(
        intent,
        blob,
        entities=entities,
        seller_operational_request_type=seller_operational_request_type,
    )
    return refined


def _is_vague_passive_notification(
    intent: VendorTicketIntent,
    blob: str,
    *,
    entities: _EntityFields | Any | None,
) -> bool:
    if intent != VendorTicketIntent.SELLER_NOTIFICATION:
        return False
    if _seller_asks_operational_action(blob) or _has_operational_conceptual_intent(blob):
        return False
    if _first_tracking_only(blob, entities):
        return False
    if _has_extracted_entities(entities):
        return False
    return True


def monitor_fallback_allowed(
    *,
    normalized_text: str = "",
    conceptual_intent_fa: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entities: _EntityFields | Any | None = None,
    seller_intent_type: str | None = None,
    seller_operational_request_type: str | None = None,
) -> bool:
    """Monitor is reserved for passive, informational, or unclear low-action tickets."""
    if is_operational_request(
        normalized_text=normalized_text,
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=detected_intent,
        entities=entities,
        seller_intent_type=seller_intent_type,
        seller_operational_request_type=seller_operational_request_type,
    ):
        return False

    intent = (
        _resolve_intent(detected_intent)
        if detected_intent is not None
        else VendorTicketIntent.UNKNOWN
    )
    blob = _conceptual_blob(conceptual_intent_fa, normalized_text)

    if _is_tracking_notification_only(intent, blob, entities=entities):
        return False
    if action_requires_specific_followup(intent):
        return False

    if _is_passive_greeting_or_noop(blob):
        return True
    if intent in (VendorTicketIntent.GENERAL_VENDOR_SUPPORT, VendorTicketIntent.UNKNOWN):
        if not _has_extracted_entities(entities):
            return True
    if seller_intent_type == "seller_notification":
        return True
    return intent in (VendorTicketIntent.GENERAL_VENDOR_SUPPORT, VendorTicketIntent.UNKNOWN)


def _mapping(
    action: VendorTicketAIAssistActionType,
    reason: str,
    *,
    operational_context: bool = False,
    monitor_suppressed: bool = False,
    monitor_suppression_reason: str | None = None,
    fallback_reason: str | None = None,
) -> SuggestedActionMapping:
    return SuggestedActionMapping(
        action=action,
        reason=reason,
        monitor_blocked_by_operational_signals=operational_context
        and action != SuggestedAction.MONITOR,
        monitor_suppressed=monitor_suppressed,
        monitor_suppression_reason=monitor_suppression_reason,
        fallback_reason=fallback_reason,
    )


def _resolve_operational_specific_action(
    intent: VendorTicketIntent,
    blob: str,
    *,
    entities: _EntityFields | Any | None,
    seller_operational_request_type: str | None,
) -> SuggestedActionMapping | None:
    """Map operational signals to a specific action when intent alone would fall back to monitor."""
    if seller_operational_request_type == "delivery_confirmation_request":
        return _mapping(
            SuggestedAction.UPDATE_DELIVERY_STATUS,
            "Step 169 operational request: delivery confirmation",
            operational_context=True,
        )
    if seller_operational_request_type == "product_approval_review":
        return _mapping(
            SuggestedAction.CHECK_PRODUCT_APPROVAL,
            "Step 169 operational request: product approval",
            operational_context=True,
        )
    if seller_operational_request_type == "order_status_review":
        return _mapping(
            SuggestedAction.CHECK_ORDER_STATUS,
            "Step 169 operational request: order status",
            operational_context=True,
        )
    if seller_operational_request_type == "settlement_status_review":
        return _mapping(
            SuggestedAction.CHECK_SETTLEMENT_STATUS,
            "Step 169 operational request: settlement status",
            operational_context=True,
        )

    if (
        _has_any(blob, _DELIVERY_CONCEPTUAL_MARKERS)
        or intent == VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST
    ):
        if _has_extracted_entities(entities) or "تحویل" in blob:
            return _mapping(
                SuggestedAction.UPDATE_DELIVERY_STATUS,
                "delivery confirmation with operational signals",
                operational_context=True,
            )

    if (
        _has_any(blob, _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS)
        or intent == VendorTicketIntent.PRODUCT_APPROVAL_REVIEW
    ):
        return _mapping(
            SuggestedAction.CHECK_PRODUCT_APPROVAL,
            "product approval with operational signals",
            operational_context=True,
        )

    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        return _mapping(
            SuggestedAction.REVIEW_PRODUCT_EDIT,
            "product edit request",
            operational_context=True,
        )

    if (
        _has_any(blob, _ORDER_STATUS_CONCEPTUAL_MARKERS)
        or intent == VendorTicketIntent.ORDER_STATUS_REVIEW
    ):
        return _mapping(
            SuggestedAction.CHECK_ORDER_STATUS,
            "order status with operational signals",
            operational_context=True,
        )

    if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_SETTLEMENT_STATUS,
            "settlement operational issue (panel/payout)",
            operational_context=True,
        )

    if _has_extracted_entities(entities):
        order_ids = getattr(entities, "extracted_order_ids", None) or []
        product_ids = getattr(entities, "extracted_product_ids", None) or []
        if order_ids and _has_any(blob, _DELIVERY_CONCEPTUAL_MARKERS):
            return _mapping(
                SuggestedAction.UPDATE_DELIVERY_STATUS,
                "order id + delivery confirmation language",
                operational_context=True,
            )
        if product_ids:
            return _mapping(
                SuggestedAction.CHECK_PRODUCT_APPROVAL,
                "product id present with operational context",
                operational_context=True,
            )
        if order_ids:
            return _mapping(
                SuggestedAction.CHECK_ORDER_STATUS,
                "order id present with operational context",
                operational_context=True,
            )

    return None


def map_intent_to_suggested_action(
    detected_intent: str | VendorTicketIntent,
    *,
    conceptual_intent_fa: str | None = None,
    entities: _EntityFields | Any | None = None,
    normalized_text: str = "",
    ticket_label: str | None = None,
    route_label: str | None = None,
    seller_intent_type: str | None = None,
    seller_operational_request_type: str | None = None,
) -> SuggestedActionMapping:
    """Map taxonomy v1 intent + context to an advisory operator action (no execution)."""
    intent = _resolve_intent(detected_intent)
    label = (ticket_label or "").strip().lower()
    route = (route_label or "").strip().lower()
    blob = _conceptual_blob(conceptual_intent_fa, normalized_text)

    operational_context = is_operational_request(
        normalized_text=normalized_text,
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=intent,
        entities=entities,
        seller_intent_type=seller_intent_type,
        seller_operational_request_type=seller_operational_request_type,
    )

    if _has_any(blob, _COMPLAINT_RESOLUTION_MARKERS):
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "complaint resolution / remove complaint request",
            operational_context=True,
            fallback_reason="complaint_resolution",
        )

    if is_cancellation_request_message(blob) or intent == VendorTicketIntent.CANCELLATION_REQUEST:
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "seller cancellation request",
            operational_context=True,
            fallback_reason="cancellation_request",
        )

    if intent == VendorTicketIntent.COMPLAINT_ESCALATION:
        if _complaint_requires_escalation(blob, intent):
            return _mapping(
                SuggestedAction.ESCALATE,
                "complaint_escalation intent",
                fallback_reason="complaint_escalation",
            )

    if _has_any(blob, _COMPLAINT_CLOSE_MARKERS) and not _complaint_requires_escalation(
        blob,
        intent,
    ):
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "complaint close request (no escalation language)",
            operational_context=True,
            fallback_reason="complaint_close",
        )

    warnings = _entity_warnings(entities)
    if warnings:
        refined = _refine_request_missing_info_action(
            intent,
            blob,
            entities=entities,
            warnings=warnings,
            seller_operational_request_type=seller_operational_request_type,
        )
        if refined is not None:
            return refined
        return _mapping(
            SuggestedAction.REQUEST_MISSING_INFO,
            f"entity extraction warnings: {warnings[:80]}",
            operational_context=operational_context,
            fallback_reason="entity_warnings",
        )

    if intent == VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST or _has_any(
        blob,
        _DELIVERY_CONCEPTUAL_MARKERS,
    ):
        return _mapping(
            SuggestedAction.UPDATE_DELIVERY_STATUS,
            "delivery confirmation / ثبت تحویل",
            operational_context=operational_context,
            fallback_reason="delivery_confirmation",
        )

    if _is_tracking_notification_only(intent, blob, entities=entities):
        return _mapping(
            SuggestedAction.RECORD_UPDATE,
            "tracking code notification only",
            fallback_reason="tracking_notification",
        )

    if intent == VendorTicketIntent.TRACKING_CODE_NOTIFICATION:
        return _mapping(
            SuggestedAction.RECORD_UPDATE,
            "tracking code notification",
            fallback_reason="tracking_notification",
        )

    if intent == VendorTicketIntent.ORDER_STATUS_REVIEW or _has_any(
        blob,
        _ORDER_STATUS_CONCEPTUAL_MARKERS,
    ):
        return _mapping(
            SuggestedAction.CHECK_ORDER_STATUS,
            "order status review / پیگیری سفارش",
            operational_context=operational_context,
            fallback_reason="order_status",
        )

    if intent == VendorTicketIntent.PRODUCT_APPROVAL_REVIEW or _has_any(
        blob,
        _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS,
    ):
        return _mapping(
            SuggestedAction.CHECK_PRODUCT_APPROVAL,
            "product approval review",
            operational_context=operational_context,
            fallback_reason="product_approval",
        )

    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        return _mapping(
            SuggestedAction.REVIEW_PRODUCT_EDIT,
            "product edit / change request",
            operational_context=operational_context,
            fallback_reason="product_edit",
        )

    if _has_any(blob, _RETURN_REFUND_MARKERS):
        return _mapping(
            SuggestedAction.CHECK_RETURN_REQUEST,
            "return or refund language",
            operational_context=operational_context,
            fallback_reason="return_refund",
        )

    if _is_policy_question_only(intent, blob) or intent in (
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION,
        VendorTicketIntent.COMMISSION_POLICY_QUESTION,
    ):
        return _mapping(
            SuggestedAction.ANSWER_POLICY_QUESTION,
            f"policy/publishing question ({intent.value})",
            fallback_reason="policy_question",
        )

    if intent == VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE:
        if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS) or operational_context:
            return _mapping(
                SuggestedAction.CHECK_SETTLEMENT_STATUS,
                "settlement panel operational issue",
                operational_context=True,
                fallback_reason="settlement_operational",
            )
        return _mapping(
            SuggestedAction.BILLING_REVIEW,
            "settlement panel access issue",
            fallback_reason="settlement_panel",
        )

    if intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY:
        if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS):
            return _mapping(
                SuggestedAction.CHECK_SETTLEMENT_STATUS,
                "settlement status / operational payout issue",
                operational_context=True,
                fallback_reason="settlement_operational",
            )
        if label == "fund" or route == "billing_review":
            return _mapping(
                SuggestedAction.BILLING_REVIEW,
                "fund label or billing_review route",
                fallback_reason="fund_route",
            )
        return _mapping(
            SuggestedAction.CHECK_SETTLEMENT_STATUS,
            "settlement status inquiry",
            fallback_reason="settlement_inquiry",
        )

    if label == "fund" or route == "billing_review":
        if _has_any(blob, _SETTLEMENT_OPERATIONAL_MARKERS):
            return _mapping(
                SuggestedAction.CHECK_SETTLEMENT_STATUS,
                "fund route with settlement operational signals",
                operational_context=True,
                fallback_reason="settlement_operational",
            )
        return _mapping(
            SuggestedAction.BILLING_REVIEW,
            "fund ticket label or billing route",
            fallback_reason="fund_route",
        )

    if intent == VendorTicketIntent.SELLER_NOTIFICATION:
        if _is_vague_passive_notification(intent, blob, entities=entities):
            return _mapping(
                SuggestedAction.MONITOR,
                "vague passive seller notification",
                fallback_reason="passive_notification",
            )
        return _mapping(
            SuggestedAction.RECORD_UPDATE,
            "seller notification (informational update)",
            fallback_reason="seller_notification",
        )

    if intent == VendorTicketIntent.SELLER_OPERATIONAL_REQUEST:
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "seller operational request",
            operational_context=True,
            fallback_reason="seller_operational_request",
        )

    if _seller_asks_operational_action(blob):
        specific = _resolve_operational_specific_action(
            intent,
            blob,
            entities=entities,
            seller_operational_request_type=seller_operational_request_type,
        )
        if specific is not None:
            return specific
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "seller asks support to take action",
            operational_context=True,
            fallback_reason="seller_asks_action",
        )

    specific = _resolve_operational_specific_action(
        intent,
        blob,
        entities=entities,
        seller_operational_request_type=seller_operational_request_type,
    )
    if specific is not None:
        return specific

    if operational_context:
        return _mapping(
            SuggestedAction.HUMAN_FOLLOWUP,
            "operational signals suppress monitor fallback",
            operational_context=True,
            fallback_reason="operational_suppresses_monitor",
        )

    suppression = should_suppress_monitor(
        detected_intent=intent,
        conceptual_intent_fa=conceptual_intent_fa,
        normalized_text=normalized_text,
        entities=entities,
        seller_intent_type=seller_intent_type,
        seller_operational_request_type=seller_operational_request_type,
        ticket_label=ticket_label,
        route_label=route_label,
    )

    if monitor_fallback_allowed(
        normalized_text=normalized_text,
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=intent,
        entities=entities,
        seller_intent_type=seller_intent_type,
        seller_operational_request_type=seller_operational_request_type,
    ):
        if suppression.suppress:
            return _map_suppressed_monitor_action(
                intent,
                blob,
                entities=entities,
                seller_operational_request_type=seller_operational_request_type,
                suppression_reason=suppression.reason,
            )
        reason = "passive greeting or low-action ticket"
        if _is_passive_greeting_or_noop(blob):
            fallback = "passive_greeting"
        elif seller_intent_type == "seller_notification":
            fallback = "passive_notification"
        else:
            fallback = "unclear_passive"
        return _mapping(
            SuggestedAction.MONITOR,
            reason,
            fallback_reason=fallback,
        )

    if suppression.suppress:
        return _map_suppressed_monitor_action(
            intent,
            blob,
            entities=entities,
            seller_operational_request_type=seller_operational_request_type,
            suppression_reason=suppression.reason,
        )

    return _mapping(
        SuggestedAction.MONITOR,
        "default advisory monitor",
        fallback_reason="default_monitor",
    )
