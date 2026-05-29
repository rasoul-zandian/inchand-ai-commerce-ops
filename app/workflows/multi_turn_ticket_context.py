"""Minimal operational multi-turn ticket context (HITL-only; no autonomous loops)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.actionability_validation import (
    ActionabilityValidationResult,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
from app.workflows.shipment_delivery_decision import is_optional_postal_tracking_request_text

OPTIONAL_TRACKING_FULFILLMENT_ACK = "درخواست شما ثبت و در دست بررسی قرار گرفت."
_SHIPMENT_DECISION_AI_SOURCE = "shipment_delivery_decision"


@dataclass(frozen=True)
class _AggregatedSellerEntities:
    order_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    primary_tracking_code: str | None
    primary_iban: str | None
    entity_warnings_summary: str | None


_INTERNAL_SENDER_TYPES = frozenset({"system", "unknown"})
_VENDOR_SENDER_TYPES = frozenset({"seller", "vendor"})
_SUPPORT_SENDER_TYPES = frozenset({"support_agent", "finance_agent"})
_CLOSED_STATUS_MARKERS = frozenset(
    {
        "closed",
        "resolved",
        "done",
        "completed",
        "archived",
        "cancelled",
        "بسته",
        "بسته شده",
        "حل شده",
        "پایان یافته",
    },
)
_CLOSED_STATUSES = _CLOSED_STATUS_MARKERS
_OPEN_STATUSES = frozenset(
    {
        "open",
        "new",
        "pending",
        "pending_review",
        "pending-review",
        "in_progress",
        "in-progress",
        "waiting",
        "باز",
    },
)


class PendingRequestType(StrEnum):
    REQUESTED_ORDER_ID = "requested_order_id"
    REQUESTED_PRODUCT_ID = "requested_product_id"
    REQUESTED_TRACKING_CODE = "requested_tracking_code"
    REQUESTED_SHIPPING_METHOD = "requested_shipping_method"
    REQUESTED_SHEBA = "requested_sheba"
    REQUESTED_BRAND_NAME = "requested_brand_name"
    REQUESTED_PHOTO_FILE = "requested_photo_file"
    REQUESTED_ADDRESS = "requested_address"
    REQUESTED_CANCELLATION_CONFIRMATION = "requested_cancellation_confirmation"
    REQUESTED_DELIVERY_CONFIRMATION = "requested_delivery_confirmation"
    UNKNOWN_REQUEST = "unknown_request"


_SKIP_LATEST_SUPPORT = "latest_message_from_support"
_SKIP_CLOSED = "closed_ticket"
_SKIP_EMPTY_LATEST = "empty_latest_message"
_SKIP_NO_SELLER = "no_seller_message"
_SKIP_MALFORMED = "malformed_ticket"


_ADMIN_REQUEST_PATTERNS: tuple[tuple[PendingRequestType, tuple[str, ...]], ...] = (
    (
        PendingRequestType.REQUESTED_TRACKING_CODE,
        (
            "کد رهگیری",
            "کد پیگیری",
            "شماره رهگیری",
            "رهگیری را",
            "رهگیری را ارسال",
            "رهگیری مرسوله",
            "tracking code",
            "کد پستی",
            "کد پستی مرسوله",
            "رهگیری پستی",
            "کد رهگیری پستی",
        ),
    ),
    (
        PendingRequestType.REQUESTED_SHIPPING_METHOD,
        (
            "نحوه ارسال",
            "روش ارسال",
            "شیوه ارسال",
        ),
    ),
    (
        PendingRequestType.REQUESTED_ORDER_ID,
        (
            "شماره سفارش",
            "شناسه سفارش",
            "کد سفارش",
        ),
    ),
    (
        PendingRequestType.REQUESTED_PRODUCT_ID,
        (
            "شناسه کالا",
            "کد کالا",
            "شناسه محصول",
        ),
    ),
    (
        PendingRequestType.REQUESTED_SHEBA,
        (
            "شماره شبا",
            "شبا را",
            "شبای",
        ),
    ),
    (
        PendingRequestType.REQUESTED_PHOTO_FILE,
        (
            "عکس",
            "تصویر",
            "فایل عکس",
            "کدام عکس",
            "حذف شود",
        ),
    ),
    (
        PendingRequestType.REQUESTED_BRAND_NAME,
        (
            "نام برند",
            "برند را",
        ),
    ),
    (
        PendingRequestType.REQUESTED_ADDRESS,
        (
            "آدرس",
            "نشانی",
        ),
    ),
    (
        PendingRequestType.REQUESTED_CANCELLATION_CONFIRMATION,
        (
            "لغو را تایید",
            "تایید لغو",
            "درخواست لغو",
        ),
    ),
    (
        PendingRequestType.REQUESTED_DELIVERY_CONFIRMATION,
        (
            "تایید تحویل",
            "ثبت تحویل",
        ),
    ),
)

_FULFILLMENT_ACK_BY_TYPE: dict[PendingRequestType, str] = {
    PendingRequestType.REQUESTED_TRACKING_CODE: (
        "کد رهگیری دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_ORDER_ID: (
        "شماره سفارش دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_PRODUCT_ID: (
        "شناسه کالا دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_SHEBA: (
        "شماره شبا دریافت شد و درخواست بررسی/ثبت آن در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_PHOTO_FILE: (
        "درخواست حذف عکس موردنظر ثبت شد و در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_SHIPPING_METHOD: (
        "اطلاعات ارسال دریافت شد و در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_BRAND_NAME: (
        "نام برند دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_ADDRESS: ("آدرس دریافت شد و درخواست شما در دست بررسی قرار گرفت."),
    PendingRequestType.REQUESTED_CANCELLATION_CONFIRMATION: (
        "درخواست لغو شما ثبت شد و در دست بررسی قرار گرفت."
    ),
    PendingRequestType.REQUESTED_DELIVERY_CONFIRMATION: (
        "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    ),
    PendingRequestType.UNKNOWN_REQUEST: ("اطلاعات دریافت شد و درخواست شما در دست بررسی قرار گرفت."),
}


@dataclass(frozen=True)
class TicketTurn:
    """One meaningful ticket message in recent context."""

    message_id: str
    sender_type: str
    text: str
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingOperationalRequest:
    """Latest admin/support request before the latest seller reply."""

    request_type: PendingRequestType
    admin_message_text: str
    fulfilled: bool = False
    tracking_optional: bool = False


@dataclass(frozen=True)
class MultiTurnContextSummary:
    """Safe aggregate metadata (no transcript bodies)."""

    multi_turn_context_enabled: bool
    message_count: int
    latest_sender_type: str | None
    pending_request_type: str | None
    pending_request_fulfilled: bool
    should_generate_draft: bool
    should_skip_reason: str | None
    meaningful_message_count: int = 0
    prior_admin_request_count: int = 0


@dataclass(frozen=True)
class MultiTurnContext:
    """Operational multi-turn context for draft generation (session/HITL)."""

    room_id: str
    message_count: int
    first_sender_type: str | None
    latest_sender_type: str | None
    latest_seller_message: str | None
    latest_admin_message: str | None
    recent_turns: tuple[TicketTurn, ...]
    prior_admin_requests: tuple[PendingOperationalRequest, ...]
    seller_replies_after_last_admin: tuple[str, ...]
    extracted_order_ids_all: tuple[str, ...]
    extracted_product_ids_all: tuple[str, ...]
    extracted_tracking_codes_all: tuple[str, ...]
    extracted_iban_all: tuple[str, ...]
    latest_order_ids: tuple[str, ...]
    latest_product_ids: tuple[str, ...]
    latest_tracking_codes: tuple[str, ...]
    latest_iban: str | None
    pending_request_type: PendingRequestType | None
    pending_request_fulfilled: bool
    should_generate_draft: bool
    should_skip_reason: str | None
    multi_turn_context_enabled: bool = True
    response_target_seller_text: str = ""
    build_warning: str | None = None

    def to_summary(self) -> MultiTurnContextSummary:
        return MultiTurnContextSummary(
            multi_turn_context_enabled=self.multi_turn_context_enabled,
            message_count=self.message_count,
            meaningful_message_count=len(self.recent_turns),
            latest_sender_type=self.latest_sender_type,
            pending_request_type=(
                self.pending_request_type.value if self.pending_request_type else None
            ),
            pending_request_fulfilled=self.pending_request_fulfilled,
            should_generate_draft=self.should_generate_draft,
            should_skip_reason=self.should_skip_reason,
            prior_admin_request_count=len(self.prior_admin_requests),
        )

    def context_entities_available(self) -> dict[str, bool]:
        return {
            "order_id": bool(self.extracted_order_ids_all),
            "product_id": bool(self.extracted_product_ids_all),
            "tracking_code": bool(self.extracted_tracking_codes_all),
            "iban": bool(self.extracted_iban_all),
        }


def _normalize_sender(sender_type: str) -> str:
    return sender_type.strip().lower()


def is_meaningful_message(message: ConversationMessage | Mapping[str, Any]) -> bool:
    """Non-empty text from a non-internal sender."""
    if isinstance(message, ConversationMessage):
        sender = _normalize_sender(message.sender_type)
        text = message.text.strip()
    else:
        sender = _normalize_sender(str(message.get("sender_type") or ""))
        text = str(message.get("text") or "").strip()
    if not text:
        return False
    return sender not in _INTERNAL_SENDER_TYPES


def _is_vendor_sender(sender: str) -> bool:
    return sender in _VENDOR_SENDER_TYPES


def _is_support_sender(sender: str) -> bool:
    return sender in _SUPPORT_SENDER_TYPES


def _normalize_ticket_status(status: str | None) -> str:
    return (status or "").strip().lower()


def is_closed_ticket_status(status: str | None) -> bool:
    """Return True when a ticket status string indicates the ticket is closed."""
    normalized = _normalize_ticket_status(status)
    if not normalized:
        return False
    if normalized in _CLOSED_STATUS_MARKERS:
        return True
    compact = normalized.replace(" ", "")
    return compact in {"بسته", "بستهشده", "حلشده", "پایانیافته"}


def is_open_ticket_status(status: str | None) -> bool:
    """Return True when status is a known open/pending marker."""
    normalized = _normalize_ticket_status(status)
    if not normalized:
        return False
    if is_closed_ticket_status(normalized):
        return False
    return normalized in _OPEN_STATUSES or "pending" in normalized or normalized == "open"


def ticket_status_gating_metadata(status: str | None) -> dict[str, Any]:
    """Safe metadata for ticket status gating (unknown defaults to open-compatible)."""
    normalized = _normalize_ticket_status(status)
    if not normalized:
        return {"ticket_status_unknown": True}
    if is_closed_ticket_status(normalized):
        return {"ticket_status": normalized, "ticket_status_closed": True}
    if is_open_ticket_status(normalized):
        return {"ticket_status": normalized, "ticket_status_open": True}
    return {"ticket_status": normalized, "ticket_status_unknown": True}


def is_closed_conversation_snapshot(snapshot: ConversationTicketSnapshot) -> bool:
    """Return True when snapshot status or closed_at indicates a closed ticket."""
    if snapshot.closed_at is not None:
        return True
    return is_closed_ticket_status(snapshot.status)


def _is_closed_snapshot(snapshot: ConversationTicketSnapshot) -> bool:
    return is_closed_conversation_snapshot(snapshot)


def _is_open_snapshot(snapshot: ConversationTicketSnapshot) -> bool:
    if _is_closed_snapshot(snapshot):
        return False
    status = _normalize_ticket_status(snapshot.status)
    if not status:
        return True
    return is_open_ticket_status(status)


def collect_meaningful_messages(
    messages: Sequence[ConversationMessage],
    *,
    max_messages: int,
) -> list[ConversationMessage]:
    """Last N meaningful messages preserving chronological order."""
    meaningful = [message for message in messages if is_meaningful_message(message)]
    if max_messages <= 0:
        return meaningful
    return meaningful[-max_messages:]


def _is_ai_generated_support_message(message: ConversationMessage) -> bool:
    if message.sender_type.strip().lower() not in _SUPPORT_SENDER_TYPES:
        return False
    meta = message.metadata if isinstance(message.metadata, dict) else {}
    if meta.get("is_ai_generated") is True:
        return True
    return str(meta.get("source") or "") == "ai_assisted_draft"


def _message_to_turn(message: ConversationMessage) -> TicketTurn:
    ts = message.timestamp.isoformat() if message.timestamp is not None else None
    meta = message.metadata if isinstance(message.metadata, dict) else {}
    return TicketTurn(
        message_id=message.message_id,
        sender_type=_normalize_sender(message.sender_type),
        text=message.text.strip(),
        created_at=ts,
        metadata=dict(meta),
    )


def latest_meaningful_sender(messages: Sequence[ConversationMessage]) -> str | None:
    for message in reversed(messages):
        if is_meaningful_message(message):
            return _normalize_sender(message.sender_type)
    return None


def detect_pending_request_type(admin_text: str) -> PendingRequestType:
    normalized = normalize_persian_arabic_digits(admin_text or "")
    for request_type, markers in _ADMIN_REQUEST_PATTERNS:
        if any(marker in normalized for marker in markers):
            return request_type
    if "؟" in normalized or "لطف" in normalized or "ارسال" in normalized:
        return PendingRequestType.UNKNOWN_REQUEST
    return PendingRequestType.UNKNOWN_REQUEST


def _seller_text_fulfills_request(
    request_type: PendingRequestType,
    seller_text: str,
    *,
    aggregated: OperationalEntityExtractionResult,
    admin_message_text: str | None = None,
) -> bool:
    text = normalize_persian_arabic_digits(seller_text or "").strip()
    if not text:
        return False
    if request_type == PendingRequestType.REQUESTED_ORDER_ID:
        return bool(aggregated.order_ids)
    if request_type == PendingRequestType.REQUESTED_PRODUCT_ID:
        return bool(aggregated.product_ids)
    if request_type in {
        PendingRequestType.REQUESTED_TRACKING_CODE,
        PendingRequestType.REQUESTED_SHIPPING_METHOD,
    }:
        if aggregated.primary_tracking_code:
            return True
        if admin_message_text and is_optional_postal_tracking_request_text(admin_message_text):
            return len(text) >= 2
        digits_only = re.sub(r"\D", "", text)
        return len(digits_only) >= 10
    if request_type == PendingRequestType.REQUESTED_SHEBA:
        return bool(aggregated.primary_iban)
    if request_type == PendingRequestType.REQUESTED_PHOTO_FILE:
        return any(token in text for token in ("عکس", "تصویر", "اول", "دوم", "حذف", "این", "همان"))
    if request_type == PendingRequestType.REQUESTED_BRAND_NAME:
        return len(text) >= 2 and not text.isdigit()
    if request_type == PendingRequestType.REQUESTED_ADDRESS:
        return len(text) >= 8
    if request_type in {
        PendingRequestType.REQUESTED_CANCELLATION_CONFIRMATION,
        PendingRequestType.REQUESTED_DELIVERY_CONFIRMATION,
        PendingRequestType.UNKNOWN_REQUEST,
    }:
        return len(text) >= 2
    return False


def _aggregate_entities_from_texts(texts: Sequence[str]) -> _AggregatedSellerEntities:
    orders: list[str] = []
    products: list[str] = []
    tracking_codes: list[str] = []
    ibans: list[str] = []
    warnings: list[str] = []
    primary_tracking: str | None = None
    primary_iban: str | None = None

    for text in texts:
        if not text.strip():
            continue
        extracted = extract_operational_entities(text)
        for value in extracted.order_ids:
            if value not in orders:
                orders.append(value)
        for value in extracted.product_ids:
            if value not in products:
                products.append(value)
        if extracted.primary_tracking_code:
            code = extracted.primary_tracking_code
            if code not in tracking_codes:
                tracking_codes.append(code)
            primary_tracking = primary_tracking or code
        if extracted.primary_iban:
            iban = extracted.primary_iban
            if iban not in ibans:
                ibans.append(iban)
            primary_iban = primary_iban or iban
        if extracted.entity_warnings_summary:
            warnings.append(extracted.entity_warnings_summary)

    return _AggregatedSellerEntities(
        order_ids=tuple(orders),
        product_ids=tuple(products),
        primary_tracking_code=primary_tracking,
        primary_iban=primary_iban,
        entity_warnings_summary="; ".join(dict.fromkeys(warnings)) or None,
    )


def _detect_pending_and_fulfillment(
    recent: Sequence[TicketTurn],
) -> tuple[PendingRequestType | None, bool, tuple[PendingOperationalRequest, ...], tuple[str, ...]]:
    prior_requests: list[PendingOperationalRequest] = []
    seller_after_admin: list[str] = []
    pending_type: PendingRequestType | None = None
    fulfilled = False

    last_admin_index: int | None = None
    for index, turn in enumerate(recent):
        if not _is_support_sender(turn.sender_type):
            continue
        if str(turn.metadata.get("source") or "") == "ai_assisted_draft":
            continue
        if turn.metadata.get("is_ai_generated") is True:
            source = str(turn.metadata.get("source") or "")
            if source != _SHIPMENT_DECISION_AI_SOURCE:
                continue
        req_type = detect_pending_request_type(turn.text)
        tracking_optional = is_optional_postal_tracking_request_text(turn.text)
        prior_requests.append(
            PendingOperationalRequest(
                request_type=req_type,
                admin_message_text=turn.text,
                fulfilled=False,
                tracking_optional=tracking_optional,
            ),
        )
        last_admin_index = index
        pending_type = req_type

    if last_admin_index is not None:
        seller_texts = [
            turn.text
            for turn in recent[last_admin_index + 1 :]
            if _is_vendor_sender(turn.sender_type)
        ]
        seller_after_admin = seller_texts
        if seller_texts and pending_type is not None:
            aggregated = _aggregate_entities_from_texts(seller_texts)
            admin_text = prior_requests[-1].admin_message_text if prior_requests else None
            tracking_optional = prior_requests[-1].tracking_optional if prior_requests else False
            fulfilled = _seller_text_fulfills_request(
                pending_type,
                seller_texts[-1],
                aggregated=aggregated,
                admin_message_text=admin_text,
            )
            if prior_requests:
                prior_requests[-1] = PendingOperationalRequest(
                    request_type=pending_type,
                    admin_message_text=prior_requests[-1].admin_message_text,
                    fulfilled=fulfilled,
                    tracking_optional=tracking_optional,
                )

    return pending_type, fulfilled, tuple(prior_requests), tuple(seller_after_admin)


def build_multi_turn_context(
    snapshot: ConversationTicketSnapshot | None,
    *,
    settings: AppSettings | None = None,
    enabled: bool | None = None,
) -> MultiTurnContext:
    """Build operational multi-turn context from a conversation snapshot."""
    cfg = settings or get_settings()
    multi_enabled = cfg.multi_turn_context_enabled if enabled is None else enabled
    max_messages = cfg.multi_turn_context_max_messages

    if snapshot is None:
        return MultiTurnContext(
            room_id="",
            message_count=0,
            first_sender_type=None,
            latest_sender_type=None,
            latest_seller_message=None,
            latest_admin_message=None,
            recent_turns=(),
            prior_admin_requests=(),
            seller_replies_after_last_admin=(),
            extracted_order_ids_all=(),
            extracted_product_ids_all=(),
            extracted_tracking_codes_all=(),
            extracted_iban_all=(),
            latest_order_ids=(),
            latest_product_ids=(),
            latest_tracking_codes=(),
            latest_iban=None,
            pending_request_type=None,
            pending_request_fulfilled=False,
            should_generate_draft=False,
            should_skip_reason=_SKIP_MALFORMED,
            multi_turn_context_enabled=multi_enabled,
            build_warning="snapshot_missing",
        )

    room_id = snapshot.room_id
    all_messages = list(snapshot.messages)
    message_count = len(all_messages)
    meaningful = collect_meaningful_messages(all_messages, max_messages=max_messages)
    recent_turns = tuple(_message_to_turn(message) for message in meaningful)

    first_sender: str | None = None
    for message in all_messages:
        if is_meaningful_message(message):
            first_sender = _normalize_sender(message.sender_type)
            break
    latest_sender = latest_meaningful_sender(all_messages)

    latest_seller: str | None = None
    latest_admin: str | None = None
    for message in reversed(all_messages):
        sender = _normalize_sender(message.sender_type)
        if latest_seller is None and _is_vendor_sender(sender) and message.text.strip():
            latest_seller = message.text.strip()
        if latest_admin is None and _is_support_sender(sender) and message.text.strip():
            latest_admin = message.text.strip()
        if latest_seller and latest_admin:
            break

    seller_texts = [turn.text for turn in recent_turns if _is_vendor_sender(turn.sender_type)]
    aggregated_all = _aggregate_entities_from_texts(seller_texts)
    latest_seller_text = seller_texts[-1] if seller_texts else ""
    latest_extracted = (
        extract_operational_entities(latest_seller_text) if latest_seller_text else aggregated_all
    )

    tracking_all = (
        (aggregated_all.primary_tracking_code,) if aggregated_all.primary_tracking_code else ()
    )

    pending_type, fulfilled, prior_requests, seller_after_admin = _detect_pending_and_fulfillment(
        recent_turns,
    )

    should_generate = False
    skip_reason: str | None = None
    if not multi_enabled:
        should_generate = True
        skip_reason = None
    elif _is_closed_snapshot(snapshot):
        skip_reason = _SKIP_CLOSED
    elif latest_sender is None:
        skip_reason = _SKIP_MALFORMED
    elif _is_support_sender(latest_sender):
        skip_reason = _SKIP_LATEST_SUPPORT
    elif not _is_vendor_sender(latest_sender):
        skip_reason = _SKIP_MALFORMED
    elif not latest_seller or not latest_seller.strip():
        skip_reason = _SKIP_EMPTY_LATEST
    elif not seller_texts:
        skip_reason = _SKIP_NO_SELLER
    else:
        should_generate = True

    response_target = latest_seller.strip() if latest_seller else (latest_seller_text or "")

    return MultiTurnContext(
        room_id=room_id,
        message_count=message_count,
        first_sender_type=first_sender,
        latest_sender_type=latest_sender,
        latest_seller_message=latest_seller,
        latest_admin_message=latest_admin,
        recent_turns=recent_turns,
        prior_admin_requests=prior_requests,
        seller_replies_after_last_admin=seller_after_admin,
        extracted_order_ids_all=aggregated_all.order_ids,
        extracted_product_ids_all=aggregated_all.product_ids,
        extracted_tracking_codes_all=tracking_all,
        extracted_iban_all=(aggregated_all.primary_iban,) if aggregated_all.primary_iban else (),
        latest_order_ids=latest_extracted.order_ids,
        latest_product_ids=latest_extracted.product_ids,
        latest_tracking_codes=(
            (latest_extracted.primary_tracking_code,)
            if latest_extracted.primary_tracking_code
            else ()
        ),
        latest_iban=latest_extracted.primary_iban,
        pending_request_type=pending_type,
        pending_request_fulfilled=fulfilled,
        should_generate_draft=should_generate,
        should_skip_reason=skip_reason,
        multi_turn_context_enabled=multi_enabled,
        response_target_seller_text=response_target,
    )


def multi_turn_context_metadata_row(
    context: MultiTurnContext | MultiTurnContextSummary,
) -> dict[str, Any]:
    """Safe metadata for graph state / reports (no transcript)."""
    if isinstance(context, MultiTurnContext):
        summary = context.to_summary()
        has_orders = bool(context.extracted_order_ids_all)
        has_products = bool(context.extracted_product_ids_all)
        has_tracking = bool(context.extracted_tracking_codes_all)
        has_iban = bool(context.extracted_iban_all)
    else:
        summary = context
        has_orders = False
        has_products = False
        has_tracking = False
        has_iban = False
    row = {
        "multi_turn_context_enabled": summary.multi_turn_context_enabled,
        "multi_turn_message_count": summary.message_count,
        "multi_turn_meaningful_message_count": summary.meaningful_message_count,
        "multi_turn_latest_sender_type": summary.latest_sender_type,
        "multi_turn_pending_request_type": summary.pending_request_type,
        "multi_turn_pending_request_fulfilled": summary.pending_request_fulfilled,
        "multi_turn_should_generate_draft": summary.should_generate_draft,
        "multi_turn_skip_reason": summary.should_skip_reason,
        "multi_turn_prior_admin_request_count": summary.prior_admin_request_count,
        "multi_turn_has_order_ids": has_orders,
        "multi_turn_has_product_ids": has_products,
        "multi_turn_has_tracking": has_tracking,
        "multi_turn_has_iban": has_iban,
    }
    tracking_codes: tuple[str, ...] = ()
    if isinstance(context, MultiTurnContext):
        tracking_codes = context.extracted_tracking_codes_all
        if not tracking_codes:
            from app.tools.tracking.iran_post_tracking import (
                infer_plausible_iran_post_tracking_code_from_text,
            )

            inferred: list[str] = []
            for text in (
                context.response_target_seller_text,
                *context.seller_replies_after_last_admin,
            ):
                code = infer_plausible_iran_post_tracking_code_from_text(text)
                if code and code not in inferred:
                    inferred.append(code)
            tracking_codes = tuple(inferred)
    from app.tools.tracking.iran_post_tracking import (
        build_tracking_verification_recommendation_metadata,
    )

    row.update(
        build_tracking_verification_recommendation_metadata(
            pending_request_type=summary.pending_request_type,
            pending_request_fulfilled=summary.pending_request_fulfilled,
            tracking_codes=tracking_codes,
        ),
    )
    order_id_candidates: list[str] = []
    if isinstance(context, MultiTurnContext):
        for raw_order in context.extracted_order_ids_all:
            from app.tools.inchand.order_lookup import normalize_inchand_order_id

            normalized_order = normalize_inchand_order_id(str(raw_order))
            if normalized_order and normalized_order not in order_id_candidates:
                order_id_candidates.append(normalized_order)
        seller_text = context.response_target_seller_text
    else:
        seller_text = None
    from app.tools.inchand.order_lookup import (
        build_inchand_order_lookup_recommendation_metadata,
    )

    row.update(
        build_inchand_order_lookup_recommendation_metadata(
            order_id_candidates,
            seller_text=seller_text,
        ),
    )
    tracking_optional = False
    if isinstance(context, MultiTurnContext) and context.prior_admin_requests:
        tracking_optional = context.prior_admin_requests[-1].tracking_optional
    elif summary.pending_request_type == PendingRequestType.REQUESTED_TRACKING_CODE.value:
        tracking_optional = False
    row["multi_turn_tracking_optional"] = tracking_optional
    return row


def apply_multi_turn_metadata_to_actionability(
    metadata: Mapping[str, Any],
    validation: ActionabilityValidationResult,
) -> ActionabilityValidationResult:
    """Apply entity-availability overlay from safe multi-turn metadata."""
    if not metadata.get("multi_turn_context_enabled"):
        return validation
    missing = list(validation.missing_required_entities)
    if metadata.get("multi_turn_has_order_ids") and "order_id" in missing:
        missing = [item for item in missing if item != "order_id"]
    if metadata.get("multi_turn_has_product_ids") and "product_id" in missing:
        missing = [item for item in missing if item != "product_id"]
    if metadata.get("multi_turn_has_tracking") and "tracking_code" in missing:
        missing = [item for item in missing if item != "tracking_code"]
    actionable = not missing
    reason = validation.validation_reason
    if actionable and validation.missing_required_entities:
        reason = "multi_turn_context_fulfilled_entities"
    elif metadata.get("multi_turn_pending_request_fulfilled") and missing:
        reason = "multi_turn_pending_request_fulfilled"
    return ActionabilityValidationResult(
        actionable=actionable,
        missing_required_entities=tuple(missing),
        requested_action=validation.requested_action,
        validation_reason=reason,
        should_request_identifier=bool(missing),
    )


def apply_multi_turn_context_to_actionability(
    context: MultiTurnContext,
    validation: ActionabilityValidationResult,
) -> ActionabilityValidationResult:
    """Overlay multi-turn entity availability onto actionability (no extractor changes)."""
    missing = list(validation.missing_required_entities)
    entities = context.context_entities_available()

    if "order_id" in missing and entities.get("order_id"):
        missing = [item for item in missing if item != "order_id"]
    if "product_id" in missing and entities.get("product_id"):
        missing = [item for item in missing if item != "product_id"]
    if "tracking_code" in missing and entities.get("tracking_code"):
        missing = [item for item in missing if item != "tracking_code"]

    actionable = not missing
    reason = validation.validation_reason
    if actionable and validation.missing_required_entities:
        reason = "multi_turn_context_fulfilled_entities"
    elif context.pending_request_fulfilled and missing:
        reason = "multi_turn_pending_request_fulfilled"

    return ActionabilityValidationResult(
        actionable=actionable,
        missing_required_entities=tuple(missing),
        requested_action=validation.requested_action,
        validation_reason=reason,
        should_request_identifier=bool(missing),
    )


def pending_fulfillment_ack_for_type(
    request_type: str | None,
    *,
    tracking_optional: bool = False,
    admin_message_text: str | None = None,
) -> str | None:
    """Concise acknowledgment for a fulfilled pending request type."""
    if not request_type:
        return None
    optional = tracking_optional or (
        admin_message_text is not None
        and is_optional_postal_tracking_request_text(admin_message_text)
    )
    if optional and request_type in {
        PendingRequestType.REQUESTED_TRACKING_CODE.value,
        PendingRequestType.REQUESTED_SHIPPING_METHOD.value,
    }:
        return OPTIONAL_TRACKING_FULFILLMENT_ACK
    try:
        parsed = PendingRequestType(request_type)
    except ValueError:
        return _FULFILLMENT_ACK_BY_TYPE.get(PendingRequestType.UNKNOWN_REQUEST)
    return _FULFILLMENT_ACK_BY_TYPE.get(parsed)


def build_pending_fulfillment_ack_draft(context: MultiTurnContext) -> str | None:
    """Concise acknowledgment when seller fulfilled the latest admin request."""
    if not context.pending_request_fulfilled or context.pending_request_type is None:
        return None
    return _FULFILLMENT_ACK_BY_TYPE.get(context.pending_request_type)


def resolve_response_target_text(
    *,
    context: MultiTurnContext | None,
    fallback_first_turn: str,
    multi_turn_enabled: bool,
) -> str:
    """Choose seller text for draft/intent when multi-turn is active."""
    if multi_turn_enabled and context is not None and context.response_target_seller_text.strip():
        return context.response_target_seller_text.strip()
    return fallback_first_turn.strip()


def resolve_extraction_text_for_context(
    *,
    context: MultiTurnContext | None,
    fallback_extraction: str,
    multi_turn_enabled: bool,
) -> str:
    """Combine recent seller messages for entity extraction when multi-turn is active."""
    if not multi_turn_enabled or context is None:
        return fallback_extraction.strip()
    seller_parts = [
        turn.text for turn in context.recent_turns if _is_vendor_sender(turn.sender_type)
    ]
    if not seller_parts:
        return fallback_extraction.strip()
    combined = "\n".join(seller_parts)
    if fallback_extraction.strip() and fallback_extraction.strip() not in combined:
        return f"{fallback_extraction.strip()}\n{combined}"
    return combined


def merge_entity_dict_with_multi_turn(
    entity_dict: dict[str, Any],
    context: MultiTurnContext,
) -> dict[str, Any]:
    """Merge aggregated multi-turn entities into extracted_entities dict."""
    merged = dict(entity_dict)
    orders = list(merged.get("order_ids") or [])
    for value in context.extracted_order_ids_all:
        if value not in orders:
            orders.append(value)
    products = list(merged.get("product_ids") or [])
    for value in context.extracted_product_ids_all:
        if value not in products:
            products.append(value)
    merged["order_ids"] = orders
    merged["product_ids"] = products
    if context.extracted_tracking_codes_all:
        merged["primary_tracking_code"] = context.extracted_tracking_codes_all[-1]
    if context.latest_iban:
        merged["primary_iban"] = context.latest_iban
    merged["multi_turn_entity_overlay"] = True
    return merged
