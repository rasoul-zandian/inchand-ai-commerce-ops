"""Read-only shipment/delivery operational decision layer (HITL; no mutations)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.tools.inchand.order_lookup import (
    InchandOrderLookupResult,
    is_delivered_order_state,
    normalize_inchand_order_id,
)
from app.tools.tracking.iran_post_tracking import (
    infer_plausible_iran_post_tracking_code_from_text,
    looks_like_iran_post_tracking_code,
    normalize_tracking_code,
)
from app.workflows.operational_entity_extraction import extract_order_ids
from app.workflows.operational_information_sufficiency import (
    is_delivery_completed_seller_message,
    is_shipment_seller_message,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

_REPLY_REQUEST_ORDER_ID = "لطفاً شماره سفارش را ارسال کنید تا درخواست بررسی شود."
_REPLY_ORDER_LOOKUP_FAILED = "درخواست شما ثبت شد و برای بررسی بیشتر ارجاع می‌شود."
_REPLY_DELIVERED_IN_INCHAND = "وضعیت مرسوله: تحویل شده. درخواست شما ثبت و در دست بررسی قرار گرفت."
_REPLY_REGISTERED_REVIEW = "درخواست شما ثبت شد و در دست بررسی قرار گرفت."
_REPLY_REGISTERED_ACK = "درخواست شما ثبت و در دست بررسی قرار گرفت."
_REPLY_DELIVERY_COMPLETED_WITHOUT_TRACKING = (
    "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
)
_REPLY_REQUEST_OPTIONAL_POST_TRACKING = (
    "لطفاً روش ارسال و کد رهگیری پستی را در صورت وجود ارسال کنید."
)
_DELIVERY_ISH_TERMS = ("تحویل", "اعمال", "اعمال کنید", "اعمال بفرمایید", "اعمال فرمایید")

_CARRIER_IRAN_POST = "iran_post"
_CARRIER_TIPAX = "tipax"
_CARRIER_MAHEX = "mahex"
_CARRIER_CHAPAR = "chapar"
_CARRIER_PEYK = "peyk"
_CARRIER_SELLER_DELIVERY = "seller_delivery"
_CARRIER_UNKNOWN = "unknown"

_CARRIER_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (_CARRIER_IRAN_POST, ("پست ایران", "شرکت پست", "پست", "iran post", "iran_post")),
    (_CARRIER_TIPAX, ("تیپاکس", "tipax")),
    (_CARRIER_MAHEX, ("ماهکس", "mahex")),
    (_CARRIER_CHAPAR, ("چاپار", "chapar")),
    (_CARRIER_PEYK, ("پیک", "peyk")),
    (
        _CARRIER_SELLER_DELIVERY,
        ("ارسال توسط فروشنده", "ارسال فروشنده", "ارسال توسط فروشنده"),
    ),
)

_SHIPMENT_DELIVERY_SCENARIOS = frozenset(
    {
        "delivery_completed",
        "shipment_reshipment",
    },
)

_PII_FORBIDDEN_PANEL_KEYS = frozenset(
    {
        "user_id",
        "receiver_name",
        "sender_name",
        "product_name",
        "raw_response",
    },
)


class ShipmentDeliveryDecisionType(StrEnum):
    ORDER_ALREADY_DELIVERED_IN_INCHAND = "order_already_delivered_in_inchand"
    IRAN_POST_TRACKING_VALID = "iran_post_tracking_valid"
    IRAN_POST_TRACKING_INVALID = "iran_post_tracking_invalid"
    IRAN_POST_TRACKING_UNAVAILABLE = "iran_post_tracking_unavailable"
    NON_IRAN_POST_TRACKING_PRESENT = "non_iran_post_tracking_present"
    TRACKING_MISSING_REQUEST_REQUIRED = "tracking_missing_request_required"
    SELLER_REPLY_NO_POST_TRACKING_ACK = "seller_reply_no_post_tracking_ack"
    SELLER_PROVIDED_IRAN_POST_TRACKING_VALID = "seller_provided_iran_post_tracking_valid"
    SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID = "seller_provided_iran_post_tracking_invalid"
    SELLER_PROVIDED_IRAN_POST_TRACKING_NEEDS_VERIFICATION = (
        "seller_provided_iran_post_tracking_needs_verification"
    )
    SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK = "seller_provided_non_post_or_no_tracking_ack"
    SELLER_PROVIDED_TRACKING_NEEDS_VERIFICATION = "seller_provided_tracking_needs_verification"
    SELLER_PROVIDED_NON_IRAN_POST_TRACKING_ACK = "seller_provided_non_iran_post_tracking_ack"
    DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK = "delivery_completed_without_tracking_ack"
    ORDER_LOOKUP_FAILED = "order_lookup_failed"
    INSUFFICIENT_ORDER_IDENTIFIER = "insufficient_order_identifier"
    NOT_SHIPMENT_OR_DELIVERY_CASE = "not_shipment_or_delivery_case"


class ShipmentDeliveryDecisionReason(StrEnum):
    NO_ORDER_ID = "no_order_id"
    NOT_APPLICABLE_SCENARIO = "not_applicable_scenario"
    ORDER_LOOKUP_ERROR = "order_lookup_error"
    ORDER_NOT_FOUND = "order_not_found"
    INCHAND_MARKED_DELIVERED = "inchand_marked_delivered"
    PARCEL_IRAN_POST_VERIFIED = "parcel_iran_post_verified"
    PARCEL_IRAN_POST_INVALID = "parcel_iran_post_invalid"
    PARCEL_IRAN_POST_NOT_VERIFIED = "parcel_iran_post_not_verified"
    PARCEL_NON_IRAN_POST = "parcel_non_iran_post"
    SELLER_TRACKING_IRAN_POST_VERIFIED = "seller_tracking_iran_post_verified"
    SELLER_TRACKING_IRAN_POST_INVALID = "seller_tracking_iran_post_invalid"
    SELLER_TRACKING_NEEDS_VERIFICATION = "seller_tracking_needs_verification"
    SELLER_NON_IRAN_POST_TRACKING = "seller_non_iran_post_tracking"
    SELLER_REPLIED_WITHOUT_POST_TRACKING = "seller_replied_without_post_tracking"
    SELLER_NON_POST_DELIVERY_METHOD = "seller_non_post_delivery_method"
    MISSING_TRACKING_AND_CARRIER = "missing_tracking_and_carrier"
    OPTIONAL_POST_TRACKING_REQUEST_REQUIRED = "optional_post_tracking_request_required"
    DELIVERY_COMPLETED_NO_TRACKING = "delivery_completed_no_tracking"


class ShipmentDeliveryDataSource(StrEnum):
    SELLER_MESSAGE = "seller_message"
    INCHAND_ORDER_LOOKUP = "inchand_order_lookup"
    IRAN_POST_VERIFICATION = "iran_post_verification"
    INFERRED = "inferred"


@dataclass(frozen=True)
class ShipmentDeliveryDecisionInput:
    seller_text: str
    detected_scenario: str | None = None
    order_id: str | None = None
    order_lookup_result: Mapping[str, Any] | InchandOrderLookupResult | None = None
    order_lookup_attempted: bool = False
    seller_provided_tracking_code: str | None = None
    seller_provided_carrier: str | None = None
    iran_post_tracking_result: Mapping[str, Any] | None = None
    source_mode: str = "manual_sandbox_chat"
    tool_execution_mode: str = "manual"
    ticket_label: str | None = None
    prior_optional_postal_tracking_request_asked: bool = False
    seller_replied_after_optional_postal_tracking_request: bool = False


@dataclass(frozen=True)
class ShipmentDeliveryDecision:
    decision_type: ShipmentDeliveryDecisionType
    reasons: tuple[ShipmentDeliveryDecisionReason, ...] = ()
    data_sources: tuple[ShipmentDeliveryDataSource, ...] = ()
    order_id: str | None = None
    order_delivered_in_inchand: bool = False
    order_tracking_code: str | None = None
    carrier: str = _CARRIER_UNKNOWN
    carrier_candidate: str | None = None
    iran_post_verification_used: bool = False
    skip_iran_post_verification: bool = False
    tracking_verification_status: str | None = None
    recommended_reply_fa: str | None = None
    should_override_draft: bool = False
    requires_human_review: bool = True
    tool_recommendations: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "reasons": [reason.value for reason in self.reasons],
            "data_sources": [source.value for source in self.data_sources],
            "order_id": self.order_id,
            "order_delivered_in_inchand": self.order_delivered_in_inchand,
            "order_tracking_code": self.order_tracking_code,
            "carrier": self.carrier,
            "carrier_candidate": self.carrier_candidate,
            "iran_post_verification_used": self.iran_post_verification_used,
            "skip_iran_post_verification": self.skip_iran_post_verification,
            "tracking_verification_status": self.tracking_verification_status,
            "recommended_reply_fa": self.recommended_reply_fa,
            "should_override_draft": self.should_override_draft,
            "requires_human_review": self.requires_human_review,
            "tool_recommendations": dict(self.tool_recommendations),
        }


_OPTIONAL_POSTAL_TRACKING_REQUEST_MARKERS = (
    "روش ارسال و کد رهگیری پستی",
    "کد رهگیری پستی را در صورت وجود",
    "رهگیری پستی را در صورت وجود",
)

_NON_POST_DELIVERY_TEXT_MARKERS = (
    "پیک",
    "ارسال با پیک",
    "ارسال توسط فروشنده",
    "ارسال فروشنده",
    "تحویل حضوری",
    "تیپاکس",
    "ماهکس",
    "چاپار",
)


def is_optional_postal_tracking_request_text(text: str) -> bool:
    """True when support/AI asked for optional postal tracking (in صورت وجود)."""
    normalized = normalize_persian_arabic_digits(text or "")
    if "در صورت وجود" not in normalized:
        return False
    return any(marker in normalized for marker in _OPTIONAL_POSTAL_TRACKING_REQUEST_MARKERS)


def seller_indicates_non_post_delivery(seller_text: str) -> bool:
    """True when seller describes courier/non-post delivery without Iran Post tracking."""
    normalized = normalize_persian_arabic_digits(seller_text or "")
    if any(marker in normalized for marker in _NON_POST_DELIVERY_TEXT_MARKERS):
        return True
    carrier = normalize_carrier_name(seller_text)
    return carrier in {
        _CARRIER_TIPAX,
        _CARRIER_MAHEX,
        _CARRIER_CHAPAR,
        _CARRIER_PEYK,
        _CARRIER_SELLER_DELIVERY,
    }


def normalize_carrier_name(value: str | None) -> str:
    """Normalize carrier label to a stable slug."""
    if not value:
        return _CARRIER_UNKNOWN
    lowered = value.strip().lower()
    if not lowered:
        return _CARRIER_UNKNOWN
    for slug, markers in _CARRIER_PATTERNS:
        if any(marker in lowered for marker in markers):
            return slug
    if lowered in {
        _CARRIER_IRAN_POST,
        _CARRIER_TIPAX,
        _CARRIER_MAHEX,
        _CARRIER_CHAPAR,
        _CARRIER_PEYK,
        _CARRIER_SELLER_DELIVERY,
        _CARRIER_UNKNOWN,
    }:
        return lowered
    return _CARRIER_UNKNOWN


def order_lookup_from_safe_dict(
    payload: Mapping[str, Any] | InchandOrderLookupResult | None,
) -> InchandOrderLookupResult | None:
    if payload is None:
        return None
    if isinstance(payload, InchandOrderLookupResult):
        return payload
    if not isinstance(payload, dict):
        return None
    return InchandOrderLookupResult(
        order_id=str(payload.get("order_id") or ""),
        found=bool(payload.get("found")),
        order_status=_optional_str(payload.get("order_status")),
        payment_status=_optional_str(payload.get("payment_status")),
        created_at=_optional_str(payload.get("created_at")),
        provider_count=int(payload.get("provider_count") or 0),
        has_parcel_tracking_code=bool(payload.get("has_parcel_tracking_code")),
        primary_parcel_tracking_code=_optional_str(payload.get("primary_parcel_tracking_code")),
        primary_provider_status=_optional_str(payload.get("primary_provider_status")),
        primary_parcel_status_name=_optional_str(payload.get("primary_parcel_status_name")),
        is_delivered_in_inchand=bool(payload.get("is_delivered_in_inchand")),
        delivery_source=_optional_str(payload.get("delivery_source")),
        error_type=_optional_str(payload.get("error_type")),
        error_message=_optional_str(payload.get("error_message")),
    )


def order_has_tracking_code(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
) -> bool:
    lookup = order_lookup_from_safe_dict(result)
    if lookup is not None:
        return lookup.has_parcel_tracking_code
    if isinstance(result, Mapping):
        return bool(result.get("has_parcel_tracking_code"))
    return False


def get_primary_tracking_code(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
) -> str | None:
    lookup = order_lookup_from_safe_dict(result)
    if lookup is not None:
        return lookup.primary_parcel_tracking_code
    if isinstance(result, Mapping):
        return _optional_str(result.get("primary_parcel_tracking_code"))
    return None


def get_primary_carrier(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
    *,
    seller_text: str = "",
    seller_carrier: str | None = None,
) -> str:
    normalized_seller = normalize_carrier_name(seller_carrier)
    if normalized_seller == _CARRIER_UNKNOWN:
        normalized_seller = _carrier_from_seller_text(seller_text)
    if normalized_seller != _CARRIER_UNKNOWN:
        return normalized_seller
    code = get_primary_tracking_code(result)
    candidate = infer_carrier_candidate_from_tracking(code, seller_text=seller_text)
    if candidate != _CARRIER_UNKNOWN:
        return candidate
    return _CARRIER_UNKNOWN


def get_carrier_candidate(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
    *,
    seller_text: str = "",
    seller_carrier: str | None = None,
) -> str | None:
    normalized_seller = normalize_carrier_name(seller_carrier)
    if normalized_seller != _CARRIER_UNKNOWN:
        return normalized_seller
    code = get_primary_tracking_code(result)
    candidate = infer_carrier_candidate_from_tracking(code, seller_text=seller_text)
    return candidate if candidate != _CARRIER_UNKNOWN else None


def order_is_delivered(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
) -> bool:
    if isinstance(result, Mapping):
        if bool(result.get("is_delivered_in_inchand")):
            return True
        order_status = _optional_str(result.get("order_status"))
        if order_status and "تحویل شده" in order_status:
            return True
        providers = result.get("providers")
        if isinstance(providers, list):
            for entry in providers:
                if not isinstance(entry, dict):
                    continue
                provider_status = _optional_str(entry.get("provider_status") or entry.get("status"))
                if provider_status and "تحویل شده" in provider_status:
                    return True
                parcel = entry.get("parcel")
                if isinstance(parcel, dict):
                    status_name = _optional_str(
                        (parcel.get("status_detail") or {}).get("name")
                        if isinstance(parcel.get("status_detail"), dict)
                        else parcel.get("status_name"),
                    )
                    if status_name and any(
                        marker in status_name
                        for marker in ("تحویل مشتری", "تحویل گیرنده", "تحویل شده")
                    ):
                        return True
                    if parcel.get("status") == 1:
                        return True
    lookup = order_lookup_from_safe_dict(result)
    if lookup is not None and lookup.found:
        return is_delivered_order_state(lookup)
    return False


def get_order_delivery_status_label(
    result: Mapping[str, Any] | InchandOrderLookupResult | None,
) -> str | None:
    lookup = order_lookup_from_safe_dict(result)
    if lookup is not None:
        if lookup.primary_parcel_status_name:
            return lookup.primary_parcel_status_name
        if lookup.primary_provider_status:
            return lookup.primary_provider_status
        return lookup.order_status
    if isinstance(result, Mapping):
        return (
            _optional_str(result.get("primary_parcel_status_name"))
            or _optional_str(result.get("primary_provider_status"))
            or _optional_str(result.get("order_status"))
        )
    return None


def infer_carrier_candidate_from_tracking(
    tracking_code: str | None,
    *,
    seller_text: str = "",
) -> str:
    code = (tracking_code or "").strip()
    if code:
        plausible, _ = looks_like_iran_post_tracking_code(normalize_tracking_code(code))
        if plausible:
            return _CARRIER_IRAN_POST
    inferred = infer_plausible_iran_post_tracking_code_from_text(seller_text)
    if inferred:
        return _CARRIER_IRAN_POST
    return _CARRIER_UNKNOWN


def is_delivery_completed_operational_scenario(inp: ShipmentDeliveryDecisionInput) -> bool:
    """True when seller message is delivery-completed (not a shipment-status inquiry)."""
    scenario = (inp.detected_scenario or "").strip()
    if scenario == "delivery_completed":
        return True
    return is_delivery_completed_seller_message(inp.seller_text)


def is_shipment_or_delivery_case(
    inp: ShipmentDeliveryDecisionInput,
) -> bool:
    scenario = (inp.detected_scenario or "").strip()
    if scenario in _SHIPMENT_DELIVERY_SCENARIOS:
        return True
    if scenario == "seller_notification" and is_shipment_seller_message(inp.seller_text):
        return True
    if (inp.ticket_label or "").strip().lower() == "shipment":
        return True
    if is_delivery_completed_seller_message(inp.seller_text):
        return True
    return is_shipment_seller_message(inp.seller_text)


def assert_safe_shipment_decision_payload(payload: Mapping[str, Any]) -> None:
    """Reject PII keys from decision panel/session payloads."""

    def _walk(value: object, key: str | None = None) -> None:
        if key and key in _PII_FORBIDDEN_PANEL_KEYS:
            raise ValueError(f"forbidden shipment decision payload key: {key}")
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                _walk(child_value, str(child_key))
        elif isinstance(value, list):
            for item in value:
                _walk(item, key)

    _walk(payload)


def shipment_delivery_reflection_metadata_row(
    decision: ShipmentDeliveryDecision | None,
) -> dict[str, Any]:
    if decision is None:
        return {
            "shipment_delivery_decision_type": None,
            "order_delivered_in_inchand": False,
            "tracking_verification_status": None,
        }
    return {
        "shipment_delivery_decision_type": decision.decision_type.value,
        "order_delivered_in_inchand": decision.order_delivered_in_inchand,
        "tracking_verification_status": decision.tracking_verification_status,
    }


def decide_shipment_delivery(
    inp: ShipmentDeliveryDecisionInput,
) -> ShipmentDeliveryDecision:
    """Compute read-only shipment/delivery operational decision."""
    from app.knowledge.policy_fact_extraction import is_policy_or_informational_question

    if is_policy_or_informational_question(inp.seller_text):
        return _make_decision(
            ShipmentDeliveryDecisionType.NOT_SHIPMENT_OR_DELIVERY_CASE,
            reasons=(ShipmentDeliveryDecisionReason.NOT_APPLICABLE_SCENARIO,),
            should_override_draft=False,
            tool_recommendations=_default_tool_recommendations(order_id=None),
        )

    guarded_delivery_fallback = _can_force_delivery_decision_from_lookup(inp)
    if not is_shipment_or_delivery_case(inp) and not guarded_delivery_fallback:
        return _make_decision(
            ShipmentDeliveryDecisionType.NOT_SHIPMENT_OR_DELIVERY_CASE,
            reasons=(ShipmentDeliveryDecisionReason.NOT_APPLICABLE_SCENARIO,),
            should_override_draft=False,
            tool_recommendations=_default_tool_recommendations(order_id=None),
        )

    order_id = _resolve_order_id(inp)
    if not order_id:
        return _make_decision(
            ShipmentDeliveryDecisionType.INSUFFICIENT_ORDER_IDENTIFIER,
            reasons=(ShipmentDeliveryDecisionReason.NO_ORDER_ID,),
            data_sources=(ShipmentDeliveryDataSource.SELLER_MESSAGE,),
            recommended_reply_fa=_REPLY_REQUEST_ORDER_ID,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": None,
            },
        )

    lookup_payload = inp.order_lookup_result
    lookup = order_lookup_from_safe_dict(lookup_payload)
    if inp.order_lookup_attempted and _order_lookup_failed(lookup_payload, lookup):
        return _make_decision(
            ShipmentDeliveryDecisionType.ORDER_LOOKUP_FAILED,
            reasons=(_lookup_failure_reason(lookup_payload, lookup),),
            data_sources=(
                ShipmentDeliveryDataSource.SELLER_MESSAGE,
                ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
            ),
            order_id=order_id,
            recommended_reply_fa=_REPLY_ORDER_LOOKUP_FAILED,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": True,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": "order_lookup_failed",
            },
        )

    if lookup and lookup.found and order_is_delivered(lookup_payload):
        return _make_decision(
            ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND,
            reasons=(ShipmentDeliveryDecisionReason.INCHAND_MARKED_DELIVERED,),
            data_sources=(
                ShipmentDeliveryDataSource.SELLER_MESSAGE,
                ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
            ),
            order_id=order_id,
            order_delivered_in_inchand=True,
            order_tracking_code=get_primary_tracking_code(lookup),
            carrier=get_primary_carrier(lookup, seller_text=inp.seller_text),
            carrier_candidate=get_carrier_candidate(
                lookup,
                seller_text=inp.seller_text,
                seller_carrier=inp.seller_provided_carrier,
            ),
            skip_iran_post_verification=True,
            tracking_verification_status="skipped_delivered_in_inchand",
            recommended_reply_fa=_REPLY_DELIVERED_IN_INCHAND,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": "delivered_in_inchand",
            },
        )

    seller_tracking = _resolve_seller_tracking(inp)
    seller_carrier = normalize_carrier_name(inp.seller_provided_carrier)
    if seller_carrier == _CARRIER_UNKNOWN:
        seller_carrier = _carrier_from_seller_text(inp.seller_text)

    if lookup and lookup.found:
        parcel_code = get_primary_tracking_code(lookup)
        if parcel_code:
            return _decide_with_tracking_code(
                inp,
                order_id=order_id,
                tracking_code=parcel_code,
                carrier=get_primary_carrier(
                    lookup,
                    seller_text=inp.seller_text,
                    seller_carrier=inp.seller_provided_carrier,
                ),
                carrier_candidate=get_carrier_candidate(
                    lookup,
                    seller_text=inp.seller_text,
                    seller_carrier=inp.seller_provided_carrier,
                ),
                data_sources=(
                    ShipmentDeliveryDataSource.SELLER_MESSAGE,
                    ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
                ),
            )
        if not order_has_tracking_code(lookup_payload):
            if is_delivery_completed_operational_scenario(inp):
                return _make_decision(
                    ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK,
                    reasons=(ShipmentDeliveryDecisionReason.DELIVERY_COMPLETED_NO_TRACKING,),
                    data_sources=(
                        ShipmentDeliveryDataSource.SELLER_MESSAGE,
                        ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
                    ),
                    order_id=order_id,
                    recommended_reply_fa=_REPLY_DELIVERY_COMPLETED_WITHOUT_TRACKING,
                    should_override_draft=True,
                    skip_iran_post_verification=True,
                    tracking_verification_status="skipped_delivery_completed_no_tracking",
                    tool_recommendations={
                        "order_lookup_recommended": False,
                        "iran_post_verification_recommended": False,
                        "skip_iran_post_reason": "delivery_completed_no_tracking",
                    },
                )
            if inp.seller_replied_after_optional_postal_tracking_request:
                return _decide_no_parcel_tracking_after_seller_reply(inp, order_id=order_id)
            return _make_decision(
                ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED,
                reasons=(ShipmentDeliveryDecisionReason.OPTIONAL_POST_TRACKING_REQUEST_REQUIRED,),
                data_sources=(
                    ShipmentDeliveryDataSource.SELLER_MESSAGE,
                    ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
                ),
                order_id=order_id,
                recommended_reply_fa=_REPLY_REQUEST_OPTIONAL_POST_TRACKING,
                should_override_draft=True,
                tool_recommendations={
                    "order_lookup_recommended": False,
                    "iran_post_verification_recommended": False,
                    "skip_iran_post_reason": None,
                },
            )

    if seller_tracking:
        carrier_candidate = seller_carrier
        if carrier_candidate == _CARRIER_UNKNOWN:
            carrier_candidate = infer_carrier_candidate_from_tracking(
                seller_tracking,
                seller_text=inp.seller_text,
            )
        return _decide_with_tracking_code(
            inp,
            order_id=order_id,
            tracking_code=seller_tracking,
            carrier=carrier_candidate,
            carrier_candidate=carrier_candidate,
            data_sources=(ShipmentDeliveryDataSource.SELLER_MESSAGE,),
        )

    return _make_decision(
        ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED,
        reasons=(ShipmentDeliveryDecisionReason.MISSING_TRACKING_AND_CARRIER,),
        data_sources=(ShipmentDeliveryDataSource.SELLER_MESSAGE,),
        order_id=order_id,
        recommended_reply_fa=_REPLY_REQUEST_OPTIONAL_POST_TRACKING,
        should_override_draft=True,
        tool_recommendations={
            "order_lookup_recommended": lookup is None,
            "iran_post_verification_recommended": False,
            "skip_iran_post_reason": None,
        },
    )


def _can_force_delivery_decision_from_lookup(inp: ShipmentDeliveryDecisionInput) -> bool:
    """Guarded fallback: delivered lookup + delivery/apply terms + order id in seller text."""
    if not inp.order_lookup_result:
        return False
    if not order_is_delivered(inp.order_lookup_result):
        return False
    normalized_order_id = _resolve_order_id(inp)
    if not normalized_order_id:
        return False
    normalized_text = normalize_persian_arabic_digits(inp.seller_text or "")
    if normalized_order_id.lower() not in normalized_text.lower():
        return False
    return any(marker in normalized_text for marker in _DELIVERY_ISH_TERMS)


def _decide_no_parcel_tracking_after_seller_reply(
    inp: ShipmentDeliveryDecisionInput,
    *,
    order_id: str,
) -> ShipmentDeliveryDecision:
    """Seller replied after optional postal tracking request; order has no parcel code."""
    data_sources = (
        ShipmentDeliveryDataSource.SELLER_MESSAGE,
        ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP,
    )
    seller_tracking = _resolve_seller_tracking(inp)
    if seller_tracking:
        return _decide_seller_iran_post_after_optional_request(
            inp,
            order_id=order_id,
            tracking_code=seller_tracking,
            data_sources=data_sources,
        )
    if seller_indicates_non_post_delivery(inp.seller_text):
        return _make_decision(
            ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK,
            reasons=(ShipmentDeliveryDecisionReason.SELLER_NON_POST_DELIVERY_METHOD,),
            data_sources=data_sources,
            order_id=order_id,
            recommended_reply_fa=_REPLY_REGISTERED_ACK,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": "non_post_delivery_method",
            },
        )
    return _make_decision(
        ShipmentDeliveryDecisionType.SELLER_REPLY_NO_POST_TRACKING_ACK,
        reasons=(ShipmentDeliveryDecisionReason.SELLER_REPLIED_WITHOUT_POST_TRACKING,),
        data_sources=data_sources,
        order_id=order_id,
        recommended_reply_fa=_REPLY_REGISTERED_ACK,
        should_override_draft=True,
        tool_recommendations={
            "order_lookup_recommended": False,
            "iran_post_verification_recommended": False,
            "skip_iran_post_reason": "seller_replied_without_post_tracking",
        },
    )


def _decide_seller_iran_post_after_optional_request(
    inp: ShipmentDeliveryDecisionInput,
    *,
    order_id: str,
    tracking_code: str,
    data_sources: tuple[ShipmentDeliveryDataSource, ...],
) -> ShipmentDeliveryDecision:
    iran_result = inp.iran_post_tracking_result
    if iran_result is None:
        return _make_decision(
            ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_NEEDS_VERIFICATION,
            reasons=(ShipmentDeliveryDecisionReason.SELLER_TRACKING_NEEDS_VERIFICATION,),
            data_sources=data_sources,
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            recommended_reply_fa=None,
            should_override_draft=False,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": True,
                "skip_iran_post_reason": None,
            },
        )

    if iran_result.get("error_type"):
        return _make_decision(
            ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_UNAVAILABLE,
            reasons=(ShipmentDeliveryDecisionReason.PARCEL_IRAN_POST_NOT_VERIFIED,),
            data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            iran_post_verification_used=True,
            tracking_verification_status="unavailable",
            recommended_reply_fa=_REPLY_REGISTERED_ACK,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": True,
                "skip_iran_post_reason": "iran_post_unavailable",
            },
        )

    verified = bool(iran_result.get("verified"))
    if verified:
        status = (
            _optional_str(iran_result.get("last_event_description"))
            or _optional_str(iran_result.get("status_description"))
            or "نامشخص"
        )
        reply = (
            f"کد رهگیری پستی با موفقیت بررسی شد. وضعیت مرسوله: {status}. {_REPLY_REGISTERED_ACK}"
        )
        return _make_decision(
            ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_VALID,
            reasons=(ShipmentDeliveryDecisionReason.SELLER_TRACKING_IRAN_POST_VERIFIED,),
            data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            iran_post_verification_used=True,
            tracking_verification_status="valid",
            recommended_reply_fa=reply,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": None,
            },
        )

    reply = (
        f"کد ارسال‌شده {tracking_code} نامعتبر است. کد رهگیری پستی صحیح را در صورت وجود ارسال کنید."
    )
    return _make_decision(
        ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID,
        reasons=(ShipmentDeliveryDecisionReason.SELLER_TRACKING_IRAN_POST_INVALID,),
        data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
        order_id=order_id,
        order_tracking_code=tracking_code,
        carrier=_CARRIER_IRAN_POST,
        carrier_candidate=_CARRIER_IRAN_POST,
        iran_post_verification_used=True,
        tracking_verification_status="invalid",
        recommended_reply_fa=reply,
        should_override_draft=True,
        tool_recommendations={
            "order_lookup_recommended": False,
            "iran_post_verification_recommended": False,
            "skip_iran_post_reason": None,
        },
    )


def _decide_with_tracking_code(
    inp: ShipmentDeliveryDecisionInput,
    *,
    order_id: str,
    tracking_code: str,
    carrier: str,
    carrier_candidate: str | None,
    data_sources: tuple[ShipmentDeliveryDataSource, ...],
) -> ShipmentDeliveryDecision:
    effective_carrier = carrier
    if effective_carrier == _CARRIER_UNKNOWN:
        effective_carrier = carrier_candidate or _CARRIER_UNKNOWN
    if effective_carrier == _CARRIER_UNKNOWN:
        effective_carrier = infer_carrier_candidate_from_tracking(
            tracking_code,
            seller_text=inp.seller_text,
        )

    is_iran_post = effective_carrier == _CARRIER_IRAN_POST or (
        effective_carrier == _CARRIER_UNKNOWN
        and infer_carrier_candidate_from_tracking(tracking_code) == _CARRIER_IRAN_POST
    )

    if not is_iran_post:
        carrier_label = _carrier_display_fa(effective_carrier)
        order_has_parcel = ShipmentDeliveryDataSource.INCHAND_ORDER_LOOKUP in data_sources
        if order_has_parcel:
            reply = (
                f"کد رهگیری سفارش: {tracking_code}\n"
                f"شرکت حمل‌ونقل: {carrier_label}\n"
                "درخواست بررسی با موفقیت ثبت شد."
            )
            decision_type = ShipmentDeliveryDecisionType.NON_IRAN_POST_TRACKING_PRESENT
            reason = ShipmentDeliveryDecisionReason.PARCEL_NON_IRAN_POST
        else:
            reply = _REPLY_REGISTERED_REVIEW
            decision_type = ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_IRAN_POST_TRACKING_ACK
            reason = ShipmentDeliveryDecisionReason.SELLER_NON_IRAN_POST_TRACKING
        return _make_decision(
            decision_type,
            reasons=(reason,),
            data_sources=data_sources,
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=effective_carrier,
            carrier_candidate=carrier_candidate,
            recommended_reply_fa=reply,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": "non_iran_post_carrier",
            },
        )

    iran_result = inp.iran_post_tracking_result
    if iran_result is None:
        return _make_decision(
            ShipmentDeliveryDecisionType.SELLER_PROVIDED_TRACKING_NEEDS_VERIFICATION,
            reasons=(ShipmentDeliveryDecisionReason.PARCEL_IRAN_POST_NOT_VERIFIED,),
            data_sources=data_sources,
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            recommended_reply_fa=None,
            should_override_draft=False,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": True,
                "skip_iran_post_reason": None,
            },
        )

    if iran_result.get("error_type"):
        return _make_decision(
            ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_UNAVAILABLE,
            reasons=(ShipmentDeliveryDecisionReason.PARCEL_IRAN_POST_NOT_VERIFIED,),
            data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            iran_post_verification_used=True,
            tracking_verification_status="unavailable",
            recommended_reply_fa=_REPLY_REGISTERED_REVIEW,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": True,
                "skip_iran_post_reason": "iran_post_unavailable",
            },
        )

    verified = bool(iran_result.get("verified"))
    if verified:
        status = (
            _optional_str(iran_result.get("last_event_description"))
            or _optional_str(iran_result.get("status_description"))
            or "نامشخص"
        )
        reply = (
            "کد رهگیری معتبر است.\n"
            f"وضعیت مرسوله: {status}\n"
            "درخواست شما ثبت و در دست بررسی قرار گرفت."
        )
        return _make_decision(
            ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID,
            reasons=(ShipmentDeliveryDecisionReason.PARCEL_IRAN_POST_VERIFIED,),
            data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
            order_id=order_id,
            order_tracking_code=tracking_code,
            carrier=_CARRIER_IRAN_POST,
            carrier_candidate=_CARRIER_IRAN_POST,
            iran_post_verification_used=True,
            tracking_verification_status="valid",
            recommended_reply_fa=reply,
            should_override_draft=True,
            tool_recommendations={
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": None,
            },
        )

    reply = f"کد رهگیری {tracking_code} نامعتبر است. لطفاً کد رهگیری صحیح را ارسال کنید."
    return _make_decision(
        ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_INVALID,
        reasons=(ShipmentDeliveryDecisionReason.PARCEL_IRAN_POST_INVALID,),
        data_sources=(*data_sources, ShipmentDeliveryDataSource.IRAN_POST_VERIFICATION),
        order_id=order_id,
        order_tracking_code=tracking_code,
        carrier=_CARRIER_IRAN_POST,
        carrier_candidate=_CARRIER_IRAN_POST,
        iran_post_verification_used=True,
        tracking_verification_status="invalid",
        recommended_reply_fa=reply,
        should_override_draft=True,
        tool_recommendations={
            "order_lookup_recommended": False,
            "iran_post_verification_recommended": False,
            "skip_iran_post_reason": None,
        },
    )


def _resolve_order_id(inp: ShipmentDeliveryDecisionInput) -> str | None:
    if inp.order_id:
        normalized = normalize_inchand_order_id(inp.order_id)
        if normalized:
            return normalized
    for raw in extract_order_ids(inp.seller_text):
        normalized = normalize_inchand_order_id(raw)
        if normalized:
            return normalized
    return None


def _resolve_seller_tracking(inp: ShipmentDeliveryDecisionInput) -> str | None:
    if inp.seller_provided_tracking_code:
        return normalize_tracking_code(inp.seller_provided_tracking_code)
    inferred = infer_plausible_iran_post_tracking_code_from_text(inp.seller_text)
    if inferred:
        return inferred
    for match in re.finditer(r"\d{10,}", inp.seller_text):
        candidate = normalize_tracking_code(match.group(0))
        plausible, _ = looks_like_iran_post_tracking_code(candidate)
        if plausible:
            return candidate
    return None


def _carrier_from_seller_text(seller_text: str) -> str:
    return normalize_carrier_name(seller_text)


def _carrier_display_fa(carrier: str) -> str:
    labels = {
        _CARRIER_IRAN_POST: "پست ایران",
        _CARRIER_TIPAX: "تیپاکس",
        _CARRIER_MAHEX: "ماهکس",
        _CARRIER_CHAPAR: "چاپار",
        _CARRIER_PEYK: "پیک",
        _CARRIER_SELLER_DELIVERY: "ارسال توسط فروشنده",
        _CARRIER_UNKNOWN: "نامشخص",
    }
    return labels.get(carrier, carrier)


def _order_lookup_failed(
    payload: Mapping[str, Any] | InchandOrderLookupResult | None,
    lookup: InchandOrderLookupResult | None,
) -> bool:
    if lookup is not None:
        return not lookup.found or bool(lookup.error_type)
    if isinstance(payload, Mapping):
        return not bool(payload.get("found")) or bool(payload.get("error_type"))
    return True


def _lookup_failure_reason(
    payload: Mapping[str, Any] | InchandOrderLookupResult | None,
    lookup: InchandOrderLookupResult | None,
) -> ShipmentDeliveryDecisionReason:
    error_type = None
    if lookup is not None:
        error_type = lookup.error_type
    elif isinstance(payload, Mapping):
        error_type = _optional_str(payload.get("error_type"))
    if error_type == "not_found":
        return ShipmentDeliveryDecisionReason.ORDER_NOT_FOUND
    return ShipmentDeliveryDecisionReason.ORDER_LOOKUP_ERROR


def _default_tool_recommendations(*, order_id: str | None) -> dict[str, Any]:
    return {
        "order_lookup_recommended": bool(order_id),
        "iran_post_verification_recommended": False,
        "skip_iran_post_reason": None,
    }


def _make_decision(
    decision_type: ShipmentDeliveryDecisionType,
    *,
    reasons: tuple[ShipmentDeliveryDecisionReason, ...] = (),
    data_sources: tuple[ShipmentDeliveryDataSource, ...] = (),
    order_id: str | None = None,
    order_delivered_in_inchand: bool = False,
    order_tracking_code: str | None = None,
    carrier: str = _CARRIER_UNKNOWN,
    carrier_candidate: str | None = None,
    iran_post_verification_used: bool = False,
    skip_iran_post_verification: bool = False,
    tracking_verification_status: str | None = None,
    recommended_reply_fa: str | None = None,
    should_override_draft: bool = False,
    tool_recommendations: dict[str, Any] | None = None,
) -> ShipmentDeliveryDecision:
    return ShipmentDeliveryDecision(
        decision_type=decision_type,
        reasons=reasons,
        data_sources=data_sources,
        order_id=order_id,
        order_delivered_in_inchand=order_delivered_in_inchand,
        order_tracking_code=order_tracking_code,
        carrier=carrier,
        carrier_candidate=carrier_candidate,
        iran_post_verification_used=iran_post_verification_used,
        skip_iran_post_verification=skip_iran_post_verification,
        tracking_verification_status=tracking_verification_status,
        recommended_reply_fa=recommended_reply_fa,
        should_override_draft=should_override_draft,
        requires_human_review=True,
        tool_recommendations=(
            tool_recommendations or _default_tool_recommendations(order_id=order_id)
        ),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
