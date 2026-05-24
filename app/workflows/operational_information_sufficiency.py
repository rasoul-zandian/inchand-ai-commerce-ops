"""Operational information sufficiency — minimum required entities for seller-support tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.evals.draft_completion_calibration import is_informational_question
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
_SCENARIO_COMPLAINT = "complaint_close"

_CANCELLATION_MARKERS = (
    "لغو سفارش",
    "درخواست لغو",
    "تقاضا لغو",
    "تقاضای لغو",
    "لغو کنید",
    "لغو کن",
    "لغو شود",
    "لغو دار",
    "cancel order",
    "cancellation_request",
    "cancel_order",
)

_CANCELLATION_SUBSTRINGS = (
    "لغو شود",
    "لغو دار",
    "تقاضا لغو",
    "تقاضای لغو",
    "درخواست لغو",
    "لغو سفارش",
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
    "به مشتری تحویل شد",
    "تحویل داده شد",
    "رسیده به مشتری",
    "مرسوله به خریدار تحویل شد",
    "تحویل مشتری شد",
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
)

_CANCELLATION_REASON_PHRASES = (
    "دلیل لغو",
    "علت لغو",
    "چرا می‌خواهید لغو",
    "چرا میخواهید لغو",
    "دلیل درخواست لغو",
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


def is_cancellation_request_message(seller_text: str) -> bool:
    """True when seller requests order cancellation (overrides shipment/delivery signals)."""
    normalized = seller_text.strip().lower()
    if not normalized:
        return False
    if _has_any(normalized, _CANCELLATION_MARKERS):
        return True
    if _has_any(normalized, _CANCELLATION_SUBSTRINGS):
        return True
    return "لغو" in normalized


def is_delivery_completed_seller_message(seller_text: str) -> bool:
    """True when seller reports customer delivery completion (not shipment/reshipment)."""
    normalized = seller_text.strip().lower()
    if not normalized:
        return False
    if _has_any(normalized, _DELIVERY_COMPLETED_MARKERS):
        return True
    if "تحویل گیرنده" in normalized and "شده" in normalized:
        return True
    if "تحویل شده" in normalized and ("مشتری" in normalized or "خریدار" in normalized):
        return True
    return bool(re.search(r"سفارش.{0,40}تحویل\s*شده", normalized))


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

    if intent in _PRODUCT_APPROVAL_INTENTS or action in _PRODUCT_APPROVAL_ACTIONS:
        return _SCENARIO_PRODUCT_APPROVAL
    if "تایید کالا" in conceptual or "تأیید کالا" in conceptual:
        return _SCENARIO_PRODUCT_APPROVAL

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

    if complete:
        hints.append("Do not ask for additional details.")

    return OperationalRequirementPolicy(
        scenario=scenario,
        minimum_required_operational_entities=missing,
        operationally_complete_request=complete,
        operational_followup_requirements=followups,
        suppress_detail_requests=complete or scenario == _SCENARIO_SETTLEMENT_INFO,
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
        if _has_any(text, _CANCELLATION_REASON_PHRASES):
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
) -> tuple[str, ...]:
    """Return English operational policy hints for draft generation prompts."""
    from app.knowledge.policy_fact_extraction import (
        has_incomplete_iban_signal,
        has_valid_extracted_iban,
        is_settlement_account_operational_request,
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
    if is_settlement_account_operational_request(
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
        if _has_any(sentence, _CANCELLATION_REASON_PHRASES):
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
) -> dict[str, Any]:
    """Serialize sufficiency metrics for batch rows and graph state."""
    success = (
        result.operationally_complete_request
        and not result.over_questioning
        and not result.unnecessary_clarification
    )
    return {
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
