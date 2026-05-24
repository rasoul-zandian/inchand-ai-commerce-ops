"""Rule-based vendor ticket operational intent taxonomy v1 (shadow/HITL only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.knowledge.knowledge_models import KnowledgeDocumentType
from app.workflows.operational_entity_extraction import extract_operational_entities
from app.workflows.seller_notification_detection import (
    SellerNotificationDetectionResult,
    SellerOperationalRequestType,
    detect_seller_notification,
    normalize_persian_arabic_digits,
)

_COMPLAINT_MARKERS = (
    "شکایت",
    "اعتراض",
    "تخلف",
    "نارضایتی",
    "رسمی ثبت",
    "پیگیری حقوقی",
)

_SETTLEMENT_PANEL_MARKERS = (
    "پنل تسویه بسته",
    "قسمت تصفیه پنل بسته",
    "پنل تصفیه بسته",
    "تصفیه پنل",
    "پنل تسویه",
)

_SETTLEMENT_STATUS_MARKERS = (
    "تسویه",
    "تصفیه",
    "واریز",
    "برداشت",
    "کیف پول",
)

_PRODUCT_APPROVAL_MARKERS = (
    "کالا تایید نشده",
    "چرا تایید نشد",
    "عدم تایید کالا",
    "تایید نشد",
    "تایید نشده",
)

_PRODUCT_PUBLISHING_MARKERS = (
    "ثبت کالا",
    "انتشار کالا",
    "نام کالا",
    "عکس کالا",
)

_PROHIBITED_GOODS_MARKERS = (
    "ممنوع",
    "غیرمجاز",
    "دارویی",
    "دخانیات",
    "جنسی",
)

_DELIVERY_CONFIRMATION_MARKERS = (
    "تحویل را ثبت کنید",
    "تحویل‌شون رو ثبت کنید",
    "تحویلشون رو ثبت کنید",
)

_TRACKING_NOTIFICATION_MARKERS = (
    "کد رهگیری",
    "کد پیگیری",
    "بارکد پستی",
)

_ORDER_STATUS_MARKERS = (
    "وضعیت سفارش",
    "پیگیری سفارش",
    "سفارش کجاست",
)

_OPERATIONAL_ASK_MARKERS = (
    "ثبت کنید",
    "بررسی کنید",
    "چک کنید",
    "پیگیری کنید",
    "لطفا بررسی",
    "لطفاً بررسی",
)


class VendorTicketIntent(StrEnum):
    SETTLEMENT_STATUS_INQUIRY = "settlement_status_inquiry"
    SETTLEMENT_PANEL_ACCESS_ISSUE = "settlement_panel_access_issue"
    PRODUCT_APPROVAL_REVIEW = "product_approval_review"
    PRODUCT_PUBLISHING_QUESTION = "product_publishing_question"
    PROHIBITED_GOODS_QUESTION = "prohibited_goods_question"
    DELIVERY_CONFIRMATION_REQUEST = "delivery_confirmation_request"
    TRACKING_CODE_NOTIFICATION = "tracking_code_notification"
    ORDER_STATUS_REVIEW = "order_status_review"
    SELLER_NOTIFICATION = "seller_notification"
    SELLER_OPERATIONAL_REQUEST = "seller_operational_request"
    COMPLAINT_ESCALATION = "complaint_escalation"
    GENERAL_VENDOR_SUPPORT = "general_vendor_support"
    UNKNOWN = "unknown"


_INTENT_DOCUMENT_TYPES: dict[VendorTicketIntent, tuple[str, ...]] = {
    VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY: (
        KnowledgeDocumentType.SETTLEMENT_RULES.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE: (
        KnowledgeDocumentType.SETTLEMENT_RULES.value,
    ),
    VendorTicketIntent.PRODUCT_APPROVAL_REVIEW: (
        KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value,
    ),
    VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION: (
        KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value,
    ),
    VendorTicketIntent.PROHIBITED_GOODS_QUESTION: (
        KnowledgeDocumentType.PROHIBITED_GOODS.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST: (
        KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value,
    ),
    VendorTicketIntent.TRACKING_CODE_NOTIFICATION: (
        KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value,
    ),
    VendorTicketIntent.ORDER_STATUS_REVIEW: (
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.SELLER_NOTIFICATION: (
        KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
    ),
    VendorTicketIntent.SELLER_OPERATIONAL_REQUEST: (
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.COMPLAINT_ESCALATION: (
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.GENERAL_VENDOR_SUPPORT: (
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    VendorTicketIntent.UNKNOWN: (),
}


@dataclass(frozen=True)
class VendorTicketIntentDetectionResult:
    detected_intent: str
    confidence_band: str
    reasons: list[str] = field(default_factory=list)
    extracted_order_ids: list[str] = field(default_factory=list)
    extracted_product_ids: list[str] = field(default_factory=list)
    extracted_tracking_code: str | None = None
    extracted_tracking_carrier: str | None = None
    extracted_iban: str | None = None
    extracted_iban_masked: str | None = None
    entity_warnings_summary: str | None = None
    related_document_types: list[str] = field(default_factory=list)

    @property
    def intent(self) -> VendorTicketIntent:
        return VendorTicketIntent(self.detected_intent)


def _norm_label(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _append_reason(reasons: list[str], code: str) -> None:
    if code not in reasons:
        reasons.append(code)


def _has_any(normalized: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in normalized:
            return marker
    return None


def _confidence_band(
    *,
    intent: VendorTicketIntent,
    seller: SellerNotificationDetectionResult,
    matched_keyword: bool,
) -> str:
    if intent in (VendorTicketIntent.UNKNOWN, VendorTicketIntent.GENERAL_VENDOR_SUPPORT):
        if seller.is_detected:
            return seller.confidence_band
        return "low"
    if seller.is_detected and (seller.entities.order_ids or seller.entities.tracking_code):
        return "high" if seller.confidence_band == "high" else "medium"
    if matched_keyword or seller.is_detected:
        return "medium"
    return "low"


def _entities_from_text(
    normalized: str,
) -> tuple[list[str], list[str], str | None, str | None, str | None, str | None, str | None]:
    """Unified operational entity extraction (Step 169/170 compat fields)."""
    op = extract_operational_entities(normalized)
    carrier = op.primary_tracking_carrier
    return (
        list(op.order_ids),
        list(op.product_ids),
        op.primary_tracking_code,
        carrier.value if carrier else None,
        op.primary_iban,
        op.primary_iban_masked,
        op.entity_warnings_summary,
    )


def _map_seller_intent(
    seller: SellerNotificationDetectionResult,
    normalized: str,
    *,
    reasons: list[str],
) -> VendorTicketIntent | None:
    if not seller.is_detected:
        return None

    if seller.is_seller_notification:
        _append_reason(reasons, "seller_notification")
        if seller.entities.tracking_code or _has_any(
            normalized,
            _TRACKING_NOTIFICATION_MARKERS,
        ):
            _append_reason(reasons, "tracking_code_present")
            return VendorTicketIntent.TRACKING_CODE_NOTIFICATION
        return VendorTicketIntent.SELLER_NOTIFICATION

    if seller.is_seller_operational_request:
        _append_reason(reasons, "seller_operational_request")
        mapping = {
            SellerOperationalRequestType.DELIVERY_CONFIRMATION_REQUEST.value: (
                VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST
            ),
            SellerOperationalRequestType.PRODUCT_APPROVAL_REVIEW.value: (
                VendorTicketIntent.PRODUCT_APPROVAL_REVIEW
            ),
            SellerOperationalRequestType.SETTLEMENT_STATUS_REVIEW.value: (
                VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY
            ),
            SellerOperationalRequestType.ORDER_STATUS_REVIEW.value: (
                VendorTicketIntent.ORDER_STATUS_REVIEW
            ),
            SellerOperationalRequestType.GENERAL_SUPPORT_REQUEST.value: (
                VendorTicketIntent.SELLER_OPERATIONAL_REQUEST
            ),
        }
        op = seller.operational_request_type
        if op:
            _append_reason(reasons, f"operational:{op}")
        return mapping.get(op or "", VendorTicketIntent.SELLER_OPERATIONAL_REQUEST)

    return None


def _keyword_intent(normalized: str, *, reasons: list[str]) -> VendorTicketIntent | None:
    panel = _has_any(normalized, _SETTLEMENT_PANEL_MARKERS)
    if panel:
        _append_reason(reasons, f"keyword:{panel}")
        return VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE

    if seller_complaint := _has_any(normalized, _COMPLAINT_MARKERS):
        _append_reason(reasons, f"keyword:{seller_complaint}")
        return VendorTicketIntent.COMPLAINT_ESCALATION

    delivery = _has_any(normalized, _DELIVERY_CONFIRMATION_MARKERS)
    if delivery:
        _append_reason(reasons, f"keyword:{delivery}")
        return VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST

    prohibited = _has_any(normalized, _PROHIBITED_GOODS_MARKERS)
    if prohibited:
        _append_reason(reasons, f"keyword:{prohibited}")
        return VendorTicketIntent.PROHIBITED_GOODS_QUESTION

    approval = _has_any(normalized, _PRODUCT_APPROVAL_MARKERS)
    if approval:
        _append_reason(reasons, f"keyword:{approval}")
        return VendorTicketIntent.PRODUCT_APPROVAL_REVIEW

    publishing = _has_any(normalized, _PRODUCT_PUBLISHING_MARKERS)
    if publishing:
        _append_reason(reasons, f"keyword:{publishing}")
        return VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION

    settlement = _has_any(normalized, _SETTLEMENT_STATUS_MARKERS)
    if settlement:
        _append_reason(reasons, f"keyword:{settlement}")
        return VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY

    order_status = _has_any(normalized, _ORDER_STATUS_MARKERS)
    if order_status:
        _append_reason(reasons, f"keyword:{order_status}")
        return VendorTicketIntent.ORDER_STATUS_REVIEW

    tracking = _has_any(normalized, _TRACKING_NOTIFICATION_MARKERS)
    if tracking:
        _append_reason(reasons, f"keyword:{tracking}")
        return VendorTicketIntent.TRACKING_CODE_NOTIFICATION

    return None


def _label_intent(
    ticket_label: str | None,
    route_label: str | None,
    *,
    reasons: list[str],
) -> VendorTicketIntent | None:
    if ticket_label == "complaint" or route_label == "escalation_review":
        _append_reason(reasons, "ticket_label:complaint")
        return VendorTicketIntent.COMPLAINT_ESCALATION
    if ticket_label == "fund" or route_label == "billing_review":
        _append_reason(reasons, "ticket_label:fund")
        return VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY
    return None


def summarize_intent_reasons(reasons: list[str], *, max_chars: int = 120) -> str:
    """Compact operator-facing summary of intent rule hits."""
    if not reasons:
        return ""
    text = ", ".join(reasons[:5])
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def detect_vendor_ticket_intent(
    text: str,
    *,
    ticket_label: str | None = None,
    route_label: str | None = None,
) -> VendorTicketIntentDetectionResult:
    """Detect operational intent from safe preview text; composes Step 169 seller detection."""
    cleaned = text.strip()
    ticket_label_norm = _norm_label(ticket_label)
    route_label_norm = _norm_label(route_label)

    if not cleaned:
        empty_reasons: list[str] = ["empty_text"]
        label_intent = _label_intent(
            ticket_label_norm,
            route_label_norm,
            reasons=empty_reasons,
        )
        if label_intent:
            return VendorTicketIntentDetectionResult(
                detected_intent=label_intent.value,
                confidence_band="low",
                reasons=empty_reasons,
                related_document_types=list(_INTENT_DOCUMENT_TYPES[label_intent]),
            )
        return VendorTicketIntentDetectionResult(
            detected_intent=VendorTicketIntent.UNKNOWN.value,
            confidence_band="low",
            reasons=empty_reasons,
            related_document_types=[],
        )

    normalized = normalize_persian_arabic_digits(cleaned)
    reasons: list[str] = []
    seller = detect_seller_notification(cleaned)
    order_ids, product_ids, tracking, tracking_carrier, iban, iban_masked, entity_warnings = (
        _entities_from_text(normalized)
    )

    if seller.complaint_language_detected:
        _append_reason(reasons, "complaint_language")

    intent: VendorTicketIntent | None = None

    panel = _has_any(normalized, _SETTLEMENT_PANEL_MARKERS)
    if panel:
        _append_reason(reasons, f"keyword:{panel}")
        intent = VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE
    elif seller.complaint_language_detected or _has_any(normalized, _COMPLAINT_MARKERS):
        marker = _has_any(normalized, _COMPLAINT_MARKERS)
        if marker:
            _append_reason(reasons, f"keyword:{marker}")
        intent = VendorTicketIntent.COMPLAINT_ESCALATION
    else:
        seller_intent = _map_seller_intent(seller, normalized, reasons=reasons)
        if seller_intent is not None:
            intent = seller_intent
        else:
            intent = _keyword_intent(normalized, reasons=reasons)
            if intent is None:
                intent = _label_intent(ticket_label_norm, route_label_norm, reasons=reasons)
            if intent is None:
                if ticket_label_norm == "support" or route_label_norm == "general_vendor_support":
                    _append_reason(reasons, "fallback:general_vendor_support")
                    intent = VendorTicketIntent.GENERAL_VENDOR_SUPPORT
                else:
                    _append_reason(reasons, "fallback:unknown")
                    intent = VendorTicketIntent.UNKNOWN

    matched_keyword = any(r.startswith("keyword:") for r in reasons)
    band = _confidence_band(
        intent=intent,
        seller=seller,
        matched_keyword=matched_keyword,
    )
    if seller.reasons:
        for reason in seller.reasons[:3]:
            _append_reason(reasons, f"seller:{reason}")

    doc_types = list(_INTENT_DOCUMENT_TYPES.get(intent, ()))
    return VendorTicketIntentDetectionResult(
        detected_intent=intent.value,
        confidence_band=band,
        reasons=reasons,
        extracted_order_ids=order_ids,
        extracted_product_ids=product_ids,
        extracted_tracking_code=tracking,
        extracted_tracking_carrier=tracking_carrier,
        extracted_iban=iban,
        extracted_iban_masked=iban_masked,
        entity_warnings_summary=entity_warnings,
        related_document_types=doc_types,
    )
