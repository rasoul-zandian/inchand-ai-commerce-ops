"""Deterministic seller notification vs operational-request detection (shadow/HITL only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.workflows.cancellation_request_detection import is_cancellation_request_message
from app.workflows.operational_entity_extraction import (
    extract_operational_entities,
    normalize_digits,
)
from app.workflows.operational_entity_extraction import (
    extract_order_ids as _extract_order_ids,
)

_NOTIFICATION_MARKERS = (
    "سفارش شماره",
    "کد رهگیری",
    "کد پیگیری",
    "بارکد پستی",
    "ارسال شد",
    "تحویل پست شد",
    "مرسوله",
)

_OPERATIONAL_REQUEST_MARKERS = (
    "ثبت کنید",
    "چک کنید",
    "بررسی کنید",
    "اعلام کنید",
    "پیگیری کنید",
    "مشکل از چیه",
    "مشکل از چیست",
    "لطفا بررسی",
    "لطفاً بررسی",
    "لطفا چک",
    "لطفاً چک",
    "لطفا پیگیری",
    "لطفاً پیگیری",
)

_COMPLAINT_ESCALATION_MARKERS = (
    "شکایت",
    "اعتراض",
    "تخلف",
    "نارضایتی",
    "رسمی ثبت",
)

_SHIPMENT_STATUS_PHRASES = (
    "ارسال شد",
    "تحویل پست شد",
)

_PRODUCT_MARKERS = ("محصول", "کالا", "انتشار", "تایید محصول", "تایید کالا")
_SETTLEMENT_MARKERS = ("تسویه", "واریز", "پرداخت", "کیف پول", "برداشت")
_DELIVERY_MARKERS = ("تحویل", "ارسال", "مرسوله", "پست")
_INVENTORY_MARKERS = ("موجودی", "انبار", "inventory")


class SellerIntentType(StrEnum):
    SELLER_NOTIFICATION = "seller_notification"
    SELLER_OPERATIONAL_REQUEST = "seller_operational_request"


class SellerNotificationType(StrEnum):
    SHIPMENT_UPDATE = "shipment_update"
    TRACKING_CODE_UPDATE = "tracking_code_update"
    INVENTORY_UPDATE = "inventory_update"
    PAYMENT_UPDATE = "payment_update"
    GENERAL_NOTIFICATION = "general_notification"


class SellerOperationalRequestType(StrEnum):
    DELIVERY_CONFIRMATION_REQUEST = "delivery_confirmation_request"
    PRODUCT_APPROVAL_REVIEW = "product_approval_review"
    ORDER_STATUS_REVIEW = "order_status_review"
    SETTLEMENT_STATUS_REVIEW = "settlement_status_review"
    GENERAL_SUPPORT_REQUEST = "general_support_request"


@dataclass(frozen=True)
class SellerNotificationEntities:
    order_id: str | None = None
    order_ids: tuple[str, ...] = ()
    tracking_code: str | None = None
    shipment_status: str | None = None


@dataclass(frozen=True)
class SellerNotificationDetectionResult:
    seller_intent: str | None
    notification_type: str | None
    operational_request_type: str | None
    entities: SellerNotificationEntities
    confidence_band: str
    reasons: list[str] = field(default_factory=list)
    complaint_language_detected: bool = False

    @property
    def is_seller_notification(self) -> bool:
        return self.seller_intent == SellerIntentType.SELLER_NOTIFICATION.value

    @property
    def is_seller_operational_request(self) -> bool:
        return self.seller_intent == SellerIntentType.SELLER_OPERATIONAL_REQUEST.value

    @property
    def is_detected(self) -> bool:
        return self.seller_intent is not None


def normalize_persian_arabic_digits(text: str) -> str:
    """Map Persian/Arabic numerals to ASCII digits for pattern matching."""
    return normalize_digits(text)


def extract_order_ids(text: str) -> tuple[str, ...]:
    """Extract one or more normalized 7-digit order IDs from seller message text."""
    return _extract_order_ids(text)


def _first_tracking_code(text: str) -> str | None:
    return extract_operational_entities(text).primary_tracking_code


def _detect_shipment_status(normalized: str) -> str | None:
    for phrase in _SHIPMENT_STATUS_PHRASES:
        if phrase in normalized:
            return phrase
    return None


def _asks_operational_action(normalized: str) -> bool:
    return any(marker in normalized for marker in _OPERATIONAL_REQUEST_MARKERS)


def _has_complaint_language(normalized: str) -> bool:
    return any(marker in normalized for marker in _COMPLAINT_ESCALATION_MARKERS)


def _has_notification_signal(normalized: str, *, order_ids: tuple[str, ...]) -> bool:
    if any(marker in normalized for marker in _NOTIFICATION_MARKERS):
        return True
    return bool(order_ids) or _first_tracking_code(normalized) is not None


def _classify_notification_type(
    normalized: str,
    *,
    order_ids: tuple[str, ...],
    tracking_code: str | None,
) -> SellerNotificationType:
    if tracking_code or "کد رهگیری" in normalized or "کد پیگیری" in normalized:
        return SellerNotificationType.TRACKING_CODE_UPDATE
    if order_ids and ("ارسال" in normalized or "مرسوله" in normalized or "تحویل" in normalized):
        return SellerNotificationType.SHIPMENT_UPDATE
    if any(marker in normalized for marker in _INVENTORY_MARKERS):
        return SellerNotificationType.INVENTORY_UPDATE
    if any(marker in normalized for marker in _SETTLEMENT_MARKERS):
        return SellerNotificationType.PAYMENT_UPDATE
    return SellerNotificationType.GENERAL_NOTIFICATION


def _classify_operational_request_type(normalized: str) -> SellerOperationalRequestType:
    if any(marker in normalized for marker in _PRODUCT_MARKERS):
        return SellerOperationalRequestType.PRODUCT_APPROVAL_REVIEW
    if any(marker in normalized for marker in _SETTLEMENT_MARKERS):
        return SellerOperationalRequestType.SETTLEMENT_STATUS_REVIEW
    if any(marker in normalized for marker in _DELIVERY_MARKERS):
        return SellerOperationalRequestType.DELIVERY_CONFIRMATION_REQUEST
    if "سفارش" in normalized or "order" in normalized:
        return SellerOperationalRequestType.ORDER_STATUS_REVIEW
    return SellerOperationalRequestType.GENERAL_SUPPORT_REQUEST


def _confidence_band(
    *,
    seller_intent: SellerIntentType | None,
    order_ids: tuple[str, ...],
    tracking_code: str | None,
) -> str:
    if seller_intent is None:
        return "low"
    if len(order_ids) >= 2 and tracking_code:
        return "high"
    if order_ids and tracking_code:
        return "high"
    if order_ids or tracking_code:
        return "medium"
    if seller_intent == SellerIntentType.SELLER_OPERATIONAL_REQUEST:
        return "medium"
    return "low"


def detect_seller_notification(text: str) -> SellerNotificationDetectionResult:
    """Detect seller notification vs operational request and extract safe aggregate IDs."""
    cleaned = text.strip()
    if not cleaned:
        return SellerNotificationDetectionResult(
            seller_intent=None,
            notification_type=None,
            operational_request_type=None,
            entities=SellerNotificationEntities(),
            confidence_band="low",
            reasons=[],
        )

    normalized = normalize_persian_arabic_digits(cleaned)
    if is_cancellation_request_message(normalized):
        return SellerNotificationDetectionResult(
            seller_intent=None,
            notification_type=None,
            operational_request_type=None,
            entities=SellerNotificationEntities(),
            confidence_band="low",
            reasons=["cancellation_request_preempts_notification"],
        )

    reasons: list[str] = []
    order_ids = extract_order_ids(normalized)
    tracking_code = _first_tracking_code(normalized)
    shipment_status = _detect_shipment_status(normalized)
    complaint = _has_complaint_language(normalized)
    operational_ask = _asks_operational_action(normalized)
    notification_signal = _has_notification_signal(normalized, order_ids=order_ids)

    if not operational_ask and not notification_signal:
        return SellerNotificationDetectionResult(
            seller_intent=None,
            notification_type=None,
            operational_request_type=None,
            entities=SellerNotificationEntities(),
            confidence_band="low",
            reasons=[],
            complaint_language_detected=complaint,
        )

    if operational_ask:
        for marker in _OPERATIONAL_REQUEST_MARKERS:
            if marker in normalized:
                reasons.append(f"operational:{marker}")
        seller_intent = SellerIntentType.SELLER_OPERATIONAL_REQUEST
        operational_type = _classify_operational_request_type(normalized)
        notification_type = None
    else:
        for marker in _NOTIFICATION_MARKERS:
            if marker in normalized:
                reasons.append(f"marker:{marker}")
        seller_intent = SellerIntentType.SELLER_NOTIFICATION
        notification_type = _classify_notification_type(
            normalized,
            order_ids=order_ids,
            tracking_code=tracking_code,
        ).value
        operational_type = None

    if order_ids:
        reasons.append("extracted:order_ids")
    if tracking_code:
        reasons.append("extracted:tracking_code")
    if shipment_status:
        reasons.append(f"status:{shipment_status}")
    if complaint:
        reasons.append("complaint_language")

    primary_order = order_ids[0] if order_ids else None
    entities = SellerNotificationEntities(
        order_id=primary_order,
        order_ids=order_ids,
        tracking_code=tracking_code,
        shipment_status=shipment_status,
    )
    band = _confidence_band(
        seller_intent=seller_intent,
        order_ids=order_ids,
        tracking_code=tracking_code,
    )
    return SellerNotificationDetectionResult(
        seller_intent=seller_intent.value,
        notification_type=notification_type,
        operational_request_type=operational_type.value if operational_type else None,
        entities=entities,
        confidence_band=band,
        reasons=reasons,
        complaint_language_detected=complaint,
    )
