"""Operational information sufficiency — minimum required entities for seller-support tasks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.evals.draft_completion_calibration import is_informational_question
from app.workflows.cancellation_request_detection import (
    draft_asks_cancellation_reason,
    is_cancellation_request_message,
)
from app.workflows.operational_entity_extraction import extract_order_ids
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_ENTITY_ORDER_ID = "order_id"
_ENTITY_PRODUCT_ID = "product_id"
_ENTITY_TRACKING_CODE = "tracking_code"
_ENTITY_SHIPPING_METHOD = "shipping_method"

_SCENARIO_DELIVERY_COMPLETED = "delivery_completed"
_SCENARIO_SHIPMENT = "shipment_reshipment"
_SCENARIO_CANCELLATION = "cancellation_request"
_SCENARIO_PRODUCT_APPROVAL = "product_approval"
_SCENARIO_SETTLEMENT_INFO = "settlement_informational"
_SCENARIO_PANEL_ISSUE = "panel_issue"
_SCENARIO_COMPLAINT = "complaint_close"

_PANEL_ISSUE_MARKERS = (
    "مشکل پنل",
    "پنلم بسته",
    "پنل بسته",
    "پنل فعال نیست",
    "عدم دسترسی به پنل",
    "وارد پنل نمی",
    "محصولاتم در پنل",
    "محصولات من در پنل",
    "فروشگاهم بسته",
    "فروشگاه بسته",
    "فروشگاه غیرفعال",
    "پنل تسویه بسته",
    "امکان برداشت ندارم",
    "فعال شدن پنل",
    "مشکل ورود به پنل",
    "دسترسی به پنل",
    "پنل من",
    "پنلم",
)

_PANEL_WEAK_CONTEXT_MARKERS = (
    "مشکل",
    "بسته",
    "فعال نیست",
    "غیرفعال",
    "دسترسی",
    "ورود",
    "نمایش داده نمی",
    "حل نشد",
    "پیگیری",
)

_PANEL_ID_REQUEST_MARKERS = (
    "شناسه پنل",
    "کد پنل",
    "شناسه فروشگاه",
    "shop id",
    "panel id",
    "شناسه فروشنده",
)

_SHOP_IDENTIFIER_REQUEST_MARKERS = (
    "شناسه فروشگاه",
    "shop id",
    "shop-id",
    "store id",
    "store-id",
    "کد فروشگاه",
    "شناسه فروشنده",
    "seller id",
    "seller-id",
    "کد فروشنده",
)

_PANEL_FORBIDDEN_DRAFT_MARKERS = (
    "علت بسته شدن پنل",
    "پنل شما فعال می‌شود",
    "پنل شما فعال میشود",
    "پنل فعال می‌شود",
    "پنل فعال میشود",
)

_PANEL_CLOSURE_REASON_MARKERS = (
    "علت بسته شدن",
    "به دلیل",
    "به‌خاطر",
    "به خاطر",
    "طبق اعلام",
    "اطلاع‌رسانی شد",
    "اطلاع رسانی شد",
    "به علت",
)

PANEL_ISSUE_NAZER_REVIEW_RESPONSE = (
    "سلام، پنل شما توسط ناظر مورد بررسی بیشتر قرار می‌گیرد و نتیجه به شما اطلاع داده می‌شود."
)

PANEL_ISSUE_NAZER_REVIEW_RESPONSE_ALT = (
    "سلام، موضوع پنل شما برای بررسی بیشتر به ناظر ارجاع می‌شود و نتیجه اطلاع‌رسانی خواهد شد."
)

_DELIVERY_INTENTS = frozenset(
    {
        VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        "delivery_confirmation",
        "shipment_sent",
        "resend_order",
    },
)

_DELIVERY_ACTIONS = frozenset({"update_delivery_status", "record_update"})

_DELIVERY_COMPLETED_MARKERS = (
    "تحویل مشتری شده",
    "تحویل گیرنده شده",
    "تحویل دادم",
    "تحویل داده ام",
    "تحویل داده‌ام",
    "تحویل مشتری دادم",
    "تحویل مشتری شد",
    "تحویل گیرنده شد",
    "به مشتری تحویل شد",
    "تحویل داده شد",
    "تحویل داده شده",
    "رسیده به مشتری",
    "مرسوله به خریدار تحویل شد",
    "تحویل مشتری شد",
    "تحویل شده",
    "تحویل شد",
)

_DELIVERY_COMPLETED_SPECIAL_PHRASES = (
    # Customer phone/OTP/delivery-code issues (secondary details)
    "گوشی مشتری خاموشه",
    "مشتری گوشیش خاموشه",
    "گوشی مشتری خاموش است",
    "کد تحویل",
    "کد تایید تحویل",
    "کد دریافت",
    "otp",
    "کد پیامک",
    "پیامک",
)

_DELIVERY_COMPLETED_TROUBLESHOOTING_ADVICE_MARKERS = (
    # Draft/advice phrases we must suppress for delivered-to-customer reports.
    "منتظر بمانید",
    "منتظر بمانید تا",
    "گوشی روشن",
    "شماره تماس",
    "شماره تماس مشتری",
    "با مشتری تماس",
    "تماس بگیرید",
    "کد تحویل",
    "کد تایید تحویل",
    "کد دریافت",
    "otp",
    "OTP",
    "کد پیامک",
    "پیامک",
)

_SHIPMENT_MARKERS = (
    "ارسال شد",
    "مجدداً ارسال شد",
    "مجددا ارسال شد",
    "برای مشتری ارسال",
    "تحویل پست شد",
    "ارسال مرسوله",
)

_SHIPMENT_INTENT_FALLBACK_MARKERS = (
    "ارسال شد",
    "ارسال مرسوله",
    "مرسوله",
    "کد رهگیری",
    "ثبت ارسال",
    "shipment",
)

_TRACKING_SHIPPING_ASK_MARKERS = (
    "کد رهگیری",
    "کد پیگیری",
    "نحوه ارسال",
    "روش ارسال",
    "شیوه ارسال",
    "لطفاً نحوه ارسال",
    "لطفا نحوه ارسال",
    "tracking",
    "shipping method",
)

_DELIVERY_APPLY_MARKERS = (
    "اعمال",
    "اعمال کنید",
    "اعمال بفرمایید",
    "اعمال فرمایید",
)

_PRODUCT_APPROVAL_INTENTS = frozenset(
    {
        VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        "product_approval",
        "product_approval_review",
    },
)

_PRODUCT_APPROVAL_ACTIONS = frozenset(
    {"check_product_approval", "review_product_edit", "review_product_status"},
)

_COMPLAINT_INTENTS = frozenset(
    {
        VendorTicketIntent.COMPLAINT_ESCALATION.value,
        "complaint_escalation",
        "complaint_close",
        "complaint_removal",
    },
)

_UNNECESSARY_DETAIL_PHRASES = (
    "لطفاً جزئیات بیشتری ارائه دهید",
    "لطفا جزئیات بیشتری ارائه دهید",
    "برای بررسی بهتر توضیح بیشتری بدهید",
    "لطفاً مشکل را کامل توضیح دهید",
    "لطفا مشکل را کامل توضیح دهید",
    "موضوع را دقیق‌تر توضیح دهید",
    "موضوع را دقیق تر توضیح دهید",
    "لطفاً توضیح بیشتری",
    "لطفا توضیح بیشتری",
    "جزئیات بیشتری درباره",
    "چه اتفاقی افتاده",
    "چه اتفاقی افتاد",
    "چه کمکی نیاز دارید",
    "چه کمکی نیاز دارین",
    "سوال خاصی دارید",
    "لطفاً مشخص کنید",
    "لطفا مشخص کنید",
    "چه درخواستی دارید",
    "چگونه می‌توانیم کمک کنیم",
    "چگونه میتونیم کمک کنیم",
)

_ISSUE_EXPLANATION_PHRASES = (
    "چه مشکلی",
    "مشکل چیست",
    "مشکل چی بود",
    "توضیح دهید چه",
    "شرح دهید",
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟])\s+")


@dataclass(frozen=True)
class OperationalRequirementPolicy:
    """Deterministic operational requirement policy for one seller-support scenario."""

    scenario: str
    minimum_required_operational_entities: tuple[str, ...]
    operationally_complete_request: bool
    operational_followup_requirements: tuple[str, ...]
    suppress_detail_requests: bool
    prompt_hints: tuple[str, ...]


@dataclass(frozen=True)
class OperationalSufficiencyResult:
    """Evaluation of whether a request has minimum operational information."""

    policy: OperationalRequirementPolicy
    operationally_complete_request: bool
    unnecessary_clarification: bool
    over_questioning: bool
    minimum_required_operational_entities: tuple[str, ...]
    operational_followup_requirements: tuple[str, ...]


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_order_ids(order_ids: tuple[str, ...]) -> bool:
    return any(str(value).strip() for value in order_ids)


def _has_product_ids(product_ids: tuple[str, ...]) -> bool:
    return any(str(value).strip() for value in product_ids)


def _has_tracking(tracking_code: str | None) -> bool:
    return bool(tracking_code and str(tracking_code).strip())


def resolve_operational_order_ids(
    seller_text: str,
    order_ids: tuple[str, ...],
    *,
    scenario: str | None = None,
) -> tuple[str, ...]:
    """Merge extracted 7-digit order IDs from seller text for operational scenarios."""
    if scenario is not None and scenario not in {
        _SCENARIO_CANCELLATION,
        _SCENARIO_DELIVERY_COMPLETED,
        _SCENARIO_SHIPMENT,
    }:
        return order_ids
    merged = list(order_ids)
    for order_id in extract_order_ids(seller_text):
        if order_id not in merged:
            merged.append(order_id)
    return tuple(merged)


def is_delivery_completed_seller_message(seller_text: str) -> bool:
    """True when seller reports customer delivery completion (not shipment/reshipment)."""
    normalized = _normalize_delivery_message_text(seller_text)
    if not normalized:
        return False
    has_order_id = bool(extract_order_ids(normalized))
    has_delivery_word = "تحویل" in normalized
    has_apply_word = _has_any(normalized, _DELIVERY_APPLY_MARKERS)
    has_customer_word = "مشتری" in normalized or "خریدار" in normalized

    if has_delivery_word and has_apply_word and (has_order_id or has_customer_word):
        return True
    if _has_any(normalized, _DELIVERY_COMPLETED_MARKERS):
        return True
    if "تحویل گیرنده" in normalized and "شده" in normalized:
        return True
    if "تحویل شده" in normalized and has_customer_word:
        return True
    # Special-case: delivery completion + code/OTP/phone-off details
    # These must not demote a delivery_completed scenario to generic support advice.
    if any(phrase in normalized for phrase in _DELIVERY_COMPLETED_SPECIAL_PHRASES) and (
        _has_any(normalized, _DELIVERY_COMPLETED_MARKERS)
        or "تحویل گیرنده" in normalized
        or ("تحویل شده" in normalized and ("مشتری" in normalized or "خریدار" in normalized))
        or bool(re.search(r"سفارش.{0,40}تحویل\s*(شده|شد)", normalized))
    ):
        return True

    return bool(re.search(r"سفارش.{0,40}تحویل\s*(شده|شد)", normalized))


def _normalize_delivery_message_text(text: str) -> str:
    normalized = text.strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"\s+", " ", normalized)
    # Common typo/noise in seller messages: "تحویل ن شده" -> intended "تحویل شده".
    normalized = re.sub(r"تحویل\s+ن\s+شده", "تحویل شده", normalized)
    return normalized


def shop_id_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Return normalized shop_id from ticket metadata when present."""
    if not metadata:
        return None
    value = metadata.get("shop_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def shop_id_available(
    *,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """True when shop/panel identifier is already known from ticket metadata."""
    resolved = (shop_id or "").strip() or (shop_id_from_metadata(metadata) or "")
    return bool(resolved)


def has_runtime_shop_identity_context(
    *,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    room_metadata: Mapping[str, Any] | None = None,
    session_state: Mapping[str, Any] | None = None,
) -> bool:
    """True when runtime/operator context already identifies the seller/shop."""
    if shop_id_available(shop_id=shop_id, metadata=metadata):
        return True
    if shop_id_available(metadata=room_metadata):
        return True
    if session_state:
        manual_shop = session_state.get("manual_sandbox_shop_id")
        if manual_shop is not None and str(manual_shop).strip():
            return True
        session_shop = session_state.get("shop_id")
        if session_shop is not None and str(session_shop).strip():
            return True
    return False


def draft_requests_shop_or_seller_identifier(draft: str) -> bool:
    """True when draft asks for shop/store/seller identifiers."""
    text = draft.strip().lower()
    if not text:
        return False
    if _has_any(text, _SHOP_IDENTIFIER_REQUEST_MARKERS):
        return True
    if "شناسه" in text and "فروشگاه" in text:
        return True
    if "شناسه" in text and "فروشنده" in text:
        return True
    return False


def detect_unnecessary_shop_identifier_request(
    draft: str,
    *,
    runtime_shop_identity_available: bool | None = None,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    room_metadata: Mapping[str, Any] | None = None,
    session_state: Mapping[str, Any] | None = None,
) -> bool:
    """True when draft asks for shop/seller ID despite runtime identity context."""
    if not draft_requests_shop_or_seller_identifier(draft):
        return False
    if runtime_shop_identity_available is not None:
        return bool(runtime_shop_identity_available)
    return has_runtime_shop_identity_context(
        shop_id=shop_id,
        metadata=metadata,
        room_metadata=room_metadata,
        session_state=session_state,
    )


def _panel_issue_preempted(
    seller_text: str,
    *,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
) -> bool:
    """True when a higher-precedence operational scenario should win over panel issue."""
    from app.knowledge.policy_fact_extraction import (
        is_settlement_account_operational_request,
        is_settlement_bank_policy_question,
        is_settlement_timing_policy_question,
    )

    text = seller_text.strip()
    if not text:
        return True
    if is_cancellation_request_message(text):
        return True
    if is_delivery_completed_seller_message(text) or is_shipment_seller_message(text):
        return True
    if is_settlement_bank_policy_question(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ) or is_settlement_timing_policy_question(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return True
    if is_settlement_account_operational_request(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return True
    normalized = text.lower()
    if "لغو" in normalized and "سفارش" in normalized:
        return True
    if any(marker in normalized for marker in ("ثبت تحویل", "تحویل شده", "تحویل مشتری")):
        return True
    if _has_product_ids(product_ids):
        if any(token in text for token in ("تایید کالا", "تأیید کالا", "شناسه کالا", "کد کالا")):
            return True
    if _has_order_ids(order_ids) and any(
        token in normalized for token in ("تحویل", "لغو", "ثبت تحویل")
    ):
        return True
    return False


def is_seller_panel_issue(
    seller_text: str,
    *,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
) -> bool:
    """True when seller message is primarily about panel/shop access or store status."""
    text = seller_text.strip()
    if not text:
        return False
    if _panel_issue_preempted(
        text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        order_ids=order_ids,
        product_ids=product_ids,
    ):
        return False
    normalized = text.lower()
    if _has_any(normalized, _PANEL_ISSUE_MARKERS):
        return True
    if "پنل" in normalized and _has_any(normalized, _PANEL_WEAK_CONTEXT_MARKERS):
        return True
    if "فروشگاه" in normalized and _has_any(
        normalized,
        ("بسته", "غیرفعال", "فعال نیست", "مشکل"),
    ):
        return True
    intent = _normalize(detected_intent)
    if intent == VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value:
        return True
    conceptual = (conceptual_intent_fa or "").strip()
    return "مشکل پنل" in conceptual or "دسترسی پنل" in conceptual


def has_known_panel_closure_reason(
    *,
    metadata: Mapping[str, Any] | None = None,
    history_text: str | None = None,
) -> bool:
    """True when prior metadata/history already explains panel closure."""
    parts: list[str] = []
    if metadata:
        for key in ("panel_closure_reason", "closure_reason", "support_note", "notes"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if history_text and history_text.strip():
        parts.append(history_text.strip())
    combined = " ".join(parts)
    if not combined:
        return False
    return _has_any(combined, _PANEL_CLOSURE_REASON_MARKERS)


def build_panel_issue_response(
    *,
    use_alternate: bool = False,
    known_closure_reason: bool = False,
) -> str:
    """Deterministic nazer-review draft for panel/shop access issues."""
    _ = known_closure_reason
    if use_alternate:
        return PANEL_ISSUE_NAZER_REVIEW_RESPONSE_ALT
    return PANEL_ISSUE_NAZER_REVIEW_RESPONSE


def draft_requests_panel_or_shop_id(draft: str) -> bool:
    """True when draft asks seller for panel/shop identifiers."""
    text = draft.strip().lower()
    if not text:
        return False
    if _has_any(text, _PANEL_ID_REQUEST_MARKERS):
        return True
    if "شناسه" in text and "پنل" in text:
        return True
    if "شناسه" in text and "فروشگاه" in text:
        return True
    return False


def draft_has_forbidden_panel_claims(draft: str) -> bool:
    """True when draft invents closure reason or promises panel reactivation."""
    text = draft.strip()
    if not text:
        return False
    if _has_any(text, _PANEL_FORBIDDEN_DRAFT_MARKERS):
        return True
    if detect_unnecessary_detail_request(text):
        return True
    return False


def apply_panel_issue_draft_calibration(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    history_text: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Replace drafts that ask for panel/shop IDs when panel issue is detected."""
    panel_detected = is_seller_panel_issue(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        order_ids=order_ids,
        product_ids=product_ids,
    )
    metrics: dict[str, Any] = {
        "panel_issue_detected": panel_detected,
        "panel_id_request_suppressed": False,
        "shop_id_available": shop_id_available(shop_id=shop_id, metadata=metadata),
    }
    if not panel_detected:
        return draft.strip(), metrics
    if has_known_panel_closure_reason(metadata=metadata, history_text=history_text):
        return draft.strip(), metrics

    cleaned = draft.strip()
    should_replace = (
        draft_requests_panel_or_shop_id(cleaned)
        or draft_has_forbidden_panel_claims(cleaned)
        or not cleaned
    )
    if should_replace:
        metrics["panel_id_request_suppressed"] = True
        return build_panel_issue_response(), metrics
    return cleaned, metrics


def refine_suggested_action_for_panel_issue(
    suggested_action: str,
    seller_text: str,
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Override request_missing_info when panel issue and shop context exists."""
    if not is_seller_panel_issue(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return suggested_action, None
    action = _normalize(suggested_action)
    if action != "request_missing_info":
        return suggested_action, None
    _ = shop_id_available(shop_id=shop_id, metadata=metadata)
    return (
        "human_followup",
        "shop_id already available from ticket metadata; panel issue requires nazer review.",
    )


def is_shipment_seller_message(seller_text: str) -> bool:
    """True when seller reports shipment/reshipment (not customer delivery completion)."""
    normalized = seller_text.strip().lower()
    if not normalized or is_delivery_completed_seller_message(seller_text):
        return False
    return _has_any(normalized, _SHIPMENT_MARKERS)


def detect_operational_scenario(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    conceptual_intent_fa: str | None = None,
) -> str:
    text = seller_text.strip()
    normalized = text.lower()
    intent = _normalize(detected_intent)
    action = _normalize(suggested_action)
    conceptual = (conceptual_intent_fa or "").strip()

    from app.knowledge.policy_fact_extraction import is_policy_or_informational_question

    if is_policy_or_informational_question(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return _SCENARIO_SETTLEMENT_INFO

    if is_cancellation_request_message(text) or "لغو" in conceptual:
        return _SCENARIO_CANCELLATION

    if is_delivery_completed_seller_message(text):
        return _SCENARIO_DELIVERY_COMPLETED

    if is_shipment_seller_message(text):
        return _SCENARIO_SHIPMENT

    if (intent in _DELIVERY_INTENTS or action in _DELIVERY_ACTIONS) and _has_any(
        normalized,
        _SHIPMENT_INTENT_FALLBACK_MARKERS,
    ):
        return _SCENARIO_SHIPMENT

    from app.knowledge.policy_fact_extraction import (
        is_settlement_account_operational_request,
        is_settlement_bank_policy_question,
        is_settlement_timing_policy_question,
    )

    if is_settlement_bank_policy_question(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ) or is_settlement_timing_policy_question(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return _SCENARIO_SETTLEMENT_INFO

    if is_settlement_account_operational_request(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return _SCENARIO_SETTLEMENT_INFO

    if intent in _PRODUCT_APPROVAL_INTENTS or action in _PRODUCT_APPROVAL_ACTIONS:
        return _SCENARIO_PRODUCT_APPROVAL
    if "تایید کالا" in conceptual or "تأیید کالا" in conceptual:
        return _SCENARIO_PRODUCT_APPROVAL

    if is_seller_panel_issue(
        text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    ):
        return _SCENARIO_PANEL_ISSUE

    if intent in {
        VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION.value,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value,
    } or action in {"check_settlement_status", "answer_policy_question"}:
        return _SCENARIO_SETTLEMENT_INFO
    if is_informational_question(text, detected_intent=detected_intent):
        return _SCENARIO_SETTLEMENT_INFO

    if intent in _COMPLAINT_INTENTS or action in {"escalate", "human_followup"}:
        if _has_any(normalized, ("شکایت", "complaint")):
            return _SCENARIO_COMPLAINT

    return "general_operational"


def _detect_scenario(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    conceptual_intent_fa: str | None = None,
) -> str:
    return detect_operational_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )


def minimum_required_operational_entities(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> tuple[str, ...]:
    """Return entity tokens still required for the operational scenario."""
    scenario = _detect_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    effective_orders = resolve_operational_order_ids(
        seller_text,
        order_ids,
        scenario=scenario,
    )
    has_order = _has_order_ids(effective_orders)
    has_product = _has_product_ids(product_ids)
    has_tracking = _has_tracking(tracking_code)

    if scenario == _SCENARIO_CANCELLATION:
        return () if has_order else (_ENTITY_ORDER_ID,)

    if scenario == _SCENARIO_DELIVERY_COMPLETED:
        return () if has_order else (_ENTITY_ORDER_ID,)

    if scenario == _SCENARIO_SHIPMENT:
        if not has_order:
            return (_ENTITY_ORDER_ID,)
        if not has_tracking:
            return (_ENTITY_TRACKING_CODE, _ENTITY_SHIPPING_METHOD)
        return ()

    if scenario == _SCENARIO_PRODUCT_APPROVAL:
        return () if has_product else (_ENTITY_PRODUCT_ID,)

    if scenario == _SCENARIO_PANEL_ISSUE:
        return ()

    if scenario in {_SCENARIO_SETTLEMENT_INFO, _SCENARIO_COMPLAINT}:
        return ()

    if not has_order and _normalize(suggested_action) in {
        "check_order_status",
    }:
        return (_ENTITY_ORDER_ID,)
    if not has_product and _normalize(suggested_action) in _PRODUCT_APPROVAL_ACTIONS:
        return (_ENTITY_PRODUCT_ID,)
    return ()


def operationally_complete_request(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> bool:
    """True when minimum operational identifiers are present for the scenario."""
    return not minimum_required_operational_entities(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )


def operational_followup_requirements(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> tuple[str, ...]:
    """Describe allowed follow-up asks when the request is not operationally complete."""
    missing = minimum_required_operational_entities(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    if not missing:
        return ("none",)
    if missing == (_ENTITY_ORDER_ID,):
        scenario = _detect_scenario(
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            conceptual_intent_fa=conceptual_intent_fa,
        )
        if scenario == _SCENARIO_DELIVERY_COMPLETED:
            return ("request_order_id_for_delivery_only",)
        if scenario == _SCENARIO_CANCELLATION:
            return ("request_order_id_for_cancellation_only",)
        return ("request_order_id_only",)
    if _ENTITY_TRACKING_CODE in missing and _ENTITY_SHIPPING_METHOD in missing:
        return ("request_tracking_and_shipping_method_only",)
    if _ENTITY_PRODUCT_ID in missing:
        return ("request_product_id_only",)
    return tuple(f"request_{entity}" for entity in missing)


def _build_policy(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> OperationalRequirementPolicy:
    scenario = _detect_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    missing = minimum_required_operational_entities(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    followups = operational_followup_requirements(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    effective_orders = resolve_operational_order_ids(
        seller_text,
        order_ids,
        scenario=scenario,
    )
    complete = not missing
    hints: list[str] = []

    if scenario == _SCENARIO_CANCELLATION:
        hints.append("cancellation_request_detected=true")
        hints.append(
            "NEVER ask for shipping method or tracking code for cancellation requests.",
        )
        if complete:
            hints.extend(
                [
                    "Do not ask for cancellation reason if order_id exists.",
                    "Acknowledge cancellation request; say it is registered/under review.",
                    "Do not ask for additional details.",
                ],
            )
        else:
            hints.append("Request order_id only; do not ask for cancellation reason yet.")

    elif scenario == _SCENARIO_DELIVERY_COMPLETED:
        hints.append(
            "NEVER ask for shipping method or tracking code for delivered-to-customer reports.",
        )
        if not _has_order_ids(effective_orders):
            hints.extend(
                [
                    "Seller reports delivery to customer — request order_id only.",
                    "Do not ask for tracking code, shipping method, or extra details.",
                ],
            )
        else:
            hints.extend(
                [
                    "Seller reports delivery to customer — acknowledge delivery request only.",
                    (
                        "If seller mentions customer phone is off, do not provide "
                        "troubleshooting advice."
                    ),
                    (
                        "If delivery code/OTP cannot be entered, acknowledge "
                        "delivery request is registered/under review."
                    ),
                    "Example: register delivery request and say it is under review.",
                    "Do not ask for tracking code, shipping method, reason, or extra details.",
                ],
            )

    elif scenario == _SCENARIO_SHIPMENT:
        hints.append(
            "Ask shipping method and tracking code ONLY when seller reports "
            "shipment/reshipment sent.",
        )
        if not _has_order_ids(effective_orders):
            hints.append("Request order_id only.")
        elif not _has_tracking(tracking_code):
            hints.extend(
                [
                    "Seller reports shipment/reshipment — if order_id exists but tracking "
                    "is missing, ask only for shipping method and tracking code.",
                    "Do not ask for issue details or what happened.",
                ],
            )
        else:
            hints.extend(
                [
                    "Shipment information is complete — acknowledge only.",
                    "Do not ask for additional details.",
                ],
            )

    elif scenario == _SCENARIO_PRODUCT_APPROVAL:
        if complete:
            hints.append("Acknowledge product review request; do not ask for extra details.")
        else:
            hints.append("Request product identifier only.")

    elif scenario == _SCENARIO_SETTLEMENT_INFO:
        hints.extend(
            [
                "Informational question — answer directly and concisely.",
                "Do not ask for additional details.",
            ],
        )

    elif scenario == _SCENARIO_COMPLAINT:
        hints.extend(
            [
                "Acknowledge complaint follow-up/review.",
                "Do not ask for full explanation again if reference exists.",
            ],
        )

    elif scenario == _SCENARIO_PANEL_ISSUE:
        hints.extend(
            [
                "Seller panel/access/store-status issue — do not ask for panel/shop/seller ID.",
                "System already has shop_id from ticket metadata when available.",
                "Do not invent panel closure reason or promise reactivation.",
                "If no known closure reason in history, say panel will be reviewed "
                "by nazer/supervisor.",
                "Do not ask for additional details or generic clarification.",
            ],
        )

    if complete:
        hints.append("Do not ask for additional details.")

    return OperationalRequirementPolicy(
        scenario=scenario,
        minimum_required_operational_entities=missing,
        operationally_complete_request=complete,
        operational_followup_requirements=followups,
        suppress_detail_requests=complete
        or scenario in {_SCENARIO_SETTLEMENT_INFO, _SCENARIO_PANEL_ISSUE},
        prompt_hints=tuple(dict.fromkeys(hints)),
    )


def evaluate_operational_sufficiency(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
    draft: str | None = None,
) -> OperationalSufficiencyResult:
    """Evaluate operational sufficiency and optional draft over-questioning signals."""
    policy = _build_policy(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    draft_text = (draft or "").strip()
    unnecessary = unnecessary_clarification_detection(draft_text, policy) if draft_text else False
    over_q = detect_over_questioning(draft_text, policy) if draft_text else False
    return OperationalSufficiencyResult(
        policy=policy,
        operationally_complete_request=policy.operationally_complete_request,
        unnecessary_clarification=unnecessary,
        over_questioning=over_q,
        minimum_required_operational_entities=policy.minimum_required_operational_entities,
        operational_followup_requirements=policy.operational_followup_requirements,
    )


def unnecessary_clarification_detection(
    draft: str,
    policy: OperationalRequirementPolicy | OperationalSufficiencyResult,
) -> bool:
    """True when draft asks for generic clarification despite operational completeness."""
    if isinstance(policy, OperationalSufficiencyResult):
        policy = policy.policy
    if not policy.suppress_detail_requests:
        return False
    text = draft.strip()
    if not text:
        return False
    return detect_unnecessary_detail_request(text)


def detect_unnecessary_detail_request(draft: str) -> bool:
    """True when draft contains generic 'provide more details' phrasing."""
    text = draft.strip()
    if not text:
        return False
    if _has_any(text, _UNNECESSARY_DETAIL_PHRASES):
        return True
    if _has_any(text, _ISSUE_EXPLANATION_PHRASES):
        return True
    return False


def detect_over_questioning(
    draft: str,
    policy: OperationalRequirementPolicy | OperationalSufficiencyResult,
) -> bool:
    """True when draft over-asks relative to operational sufficiency policy."""
    if isinstance(policy, OperationalSufficiencyResult):
        policy = policy.policy
    text = draft.strip()
    if not text:
        return False

    if unnecessary_clarification_detection(text, policy):
        return True

    if policy.scenario == _SCENARIO_CANCELLATION and policy.operationally_complete_request:
        if draft_asks_cancellation_reason(text):
            return True
        if _draft_requests_tracking_or_shipping(text):
            return True

    if policy.scenario == _SCENARIO_CANCELLATION and _draft_requests_tracking_or_shipping(text):
        return True

    if policy.scenario == _SCENARIO_DELIVERY_COMPLETED and policy.operationally_complete_request:
        if _draft_requests_tracking_or_shipping(text):
            return True
        if detect_unnecessary_detail_request(text):
            return True
        if _has_any(text, _DELIVERY_COMPLETED_TROUBLESHOOTING_ADVICE_MARKERS):
            return True

    if policy.scenario == _SCENARIO_DELIVERY_COMPLETED and _draft_requests_tracking_or_shipping(
        text
    ):
        return True

    if policy.scenario == _SCENARIO_SHIPMENT:
        followups = policy.operational_followup_requirements
        if followups == ("request_tracking_and_shipping_method_only",):
            if detect_unnecessary_detail_request(text):
                return True
            if _has_any(text, _ISSUE_EXPLANATION_PHRASES):
                return True
        if policy.operationally_complete_request and "؟" in text:
            if _has_any(text, _UNNECESSARY_DETAIL_PHRASES + _ISSUE_EXPLANATION_PHRASES):
                return True

    return False


def build_operational_policy_prompt_hints(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return English operational policy hints for draft generation prompts."""
    from app.knowledge.policy_fact_extraction import (
        has_incomplete_iban_signal,
        has_valid_extracted_iban,
        is_settlement_account_operational_request,
        is_settlement_bank_policy_question,
    )

    policy = _build_policy(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    hints = list(policy.prompt_hints)
    if is_settlement_bank_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        hints.append(
            "Seller asks which bank/account/IBAN is acceptable for settlement — "
            "answer from official settlement bank policy; do not ask seller to send Sheba.",
        )
        hints.append(
            "اگر فروشنده می‌پرسد شبا/حساب برای تسویه باید مربوط به کدام بانک باشد، "
            "پاسخ قانونی بده و درخواست ارسال شبا نکن.",
        )
    elif is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        hints.append("Never ask for photo/screenshot of Sheba.")
        if has_valid_extracted_iban(extracted_iban, seller_text):
            hints.append(
                "Extracted Sheba/IBAN is present — acknowledge review/registration; "
                "do not ask for Sheba again.",
            )
        elif has_incomplete_iban_signal(
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        ):
            hints.append(
                "Incomplete/invalid Sheba candidate detected — "
                "ask only for corrected Sheba number.",
            )
        else:
            hints.append(
                "No valid Sheba extracted — ask only for correct Sheba number; "
                "do not ask for extra details.",
            )
    if is_seller_panel_issue(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        order_ids=order_ids,
        product_ids=product_ids,
    ):
        if shop_id_available(shop_id=shop_id, metadata=metadata):
            hints.append("shop_id_available=true — never ask seller for panel/shop ID.")
        else:
            hints.append(
                "shop_id_available=false — still do not ask for panel/shop ID; use nazer review.",
            )
        hints.append("panel_issue_detected=true")
    return tuple(dict.fromkeys(hints))


def _draft_requests_tracking_or_shipping(draft: str) -> bool:
    return _has_any(draft.strip(), _TRACKING_SHIPPING_ASK_MARKERS)


def _deterministic_scenario_acknowledgment(policy: OperationalRequirementPolicy) -> str | None:
    if policy.scenario == _SCENARIO_CANCELLATION:
        if policy.operationally_complete_request:
            return "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."
        return "لطفاً شماره سفارش را ارسال کنید تا درخواست لغو بررسی شود."
    if policy.scenario == _SCENARIO_DELIVERY_COMPLETED:
        if policy.operationally_complete_request:
            return "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
        return "لطفاً شماره سفارش را ارسال کنید تا درخواست تحویل بررسی شود."
    return None


def _split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]


def _rejoin_sentences(sentences: list[str]) -> str:
    if not sentences:
        return ""
    joined = ". ".join(sentences)
    if not joined.endswith((".", "؟", "!")):
        joined += "."
    return joined


def _sentence_should_remove(sentence: str, policy: OperationalRequirementPolicy) -> bool:
    if detect_unnecessary_detail_request(sentence):
        return policy.suppress_detail_requests
    if policy.scenario in {_SCENARIO_CANCELLATION, _SCENARIO_DELIVERY_COMPLETED}:
        if _draft_requests_tracking_or_shipping(sentence):
            return True
    if policy.scenario == _SCENARIO_CANCELLATION and policy.operationally_complete_request:
        if draft_asks_cancellation_reason(sentence):
            return True
    if policy.scenario == _SCENARIO_DELIVERY_COMPLETED and policy.operationally_complete_request:
        if detect_unnecessary_detail_request(sentence):
            return True
    if policy.scenario == _SCENARIO_SHIPMENT:
        followups = policy.operational_followup_requirements
        if followups == ("request_tracking_and_shipping_method_only",):
            if _has_any(sentence, _ISSUE_EXPLANATION_PHRASES):
                return True
            if _has_any(sentence, _UNNECESSARY_DETAIL_PHRASES):
                return True
    return False


def apply_operational_sufficiency_calibration(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    order_ids: tuple[str, ...] = (),
    product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
    shop_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[str, OperationalSufficiencyResult]:
    """Remove unnecessary clarification from drafts when operationally complete."""
    policy = _build_policy(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    sentences = _split_sentences(draft)
    if not sentences:
        result = evaluate_operational_sufficiency(
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            order_ids=order_ids,
            product_ids=product_ids,
            tracking_code=tracking_code,
            conceptual_intent_fa=conceptual_intent_fa,
            draft=draft,
        )
        return draft.strip(), result

    kept = [sentence for sentence in sentences if not _sentence_should_remove(sentence, policy)]
    calibrated = _rejoin_sentences(kept).strip() or draft.strip()

    if policy.scenario in {_SCENARIO_CANCELLATION, _SCENARIO_DELIVERY_COMPLETED}:
        ack = _deterministic_scenario_acknowledgment(policy)
        if ack and (
            not calibrated.strip()
            or _draft_requests_tracking_or_shipping(calibrated)
            or detect_over_questioning(calibrated, policy)
        ):
            calibrated = ack

    if policy.scenario == _SCENARIO_PANEL_ISSUE:
        calibrated, _panel_metrics = apply_panel_issue_draft_calibration(
            calibrated,
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            conceptual_intent_fa=conceptual_intent_fa,
            order_ids=order_ids,
            product_ids=product_ids,
            shop_id=shop_id,
            metadata=metadata,
        )

    result = evaluate_operational_sufficiency(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
        draft=calibrated,
    )
    return calibrated, result


def operational_sufficiency_metrics_row(
    result: OperationalSufficiencyResult,
    *,
    panel_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize sufficiency metrics for batch rows and graph state."""
    success = (
        result.operationally_complete_request
        and not result.over_questioning
        and not result.unnecessary_clarification
    )
    row: dict[str, Any] = {
        "operational_scenario": result.policy.scenario,
        "operationally_complete_request": result.operationally_complete_request,
        "minimum_required_operational_entities": list(
            result.minimum_required_operational_entities,
        ),
        "operational_followup_requirements": list(result.operational_followup_requirements),
        "over_questioning_rate": 1.0 if result.over_questioning else 0.0,
        "unnecessary_clarification_rate": 1.0 if result.unnecessary_clarification else 0.0,
        "operational_completion_success_rate": 1.0 if success else 0.0,
    }
    if panel_metrics:
        row["panel_issue_detected"] = bool(panel_metrics.get("panel_issue_detected"))
        row["panel_id_request_suppressed"] = bool(
            panel_metrics.get("panel_id_request_suppressed"),
        )
        row["shop_id_available"] = bool(panel_metrics.get("shop_id_available"))
    elif result.policy.scenario == _SCENARIO_PANEL_ISSUE:
        row["panel_issue_detected"] = True
    return row
