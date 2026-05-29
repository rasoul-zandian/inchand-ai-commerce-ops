"""Lightweight single-pass final draft reflection (deterministic-first, HITL-safe)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.draft_evidence_wording_calibration import (
    calibrate_photo_evidence_wording,
    draft_uses_forbidden_photo_id_wording,
    should_request_photo_file,
)
from app.evals.draft_policy_grounding_calibration import apply_policy_grounding_calibration
from app.evals.draft_product_wording_calibration import apply_product_wording_calibration
from app.evals.draft_style import DRAFT_STYLE_POLICY_EXPLANATION
from app.knowledge.policy_fact_extraction import (
    COMMISSION_POLICY_FALLBACK_DRAFT_ANSWER,
    SETTLEMENT_BANK_CANONICAL_DRAFT_ANSWER,
    SETTLEMENT_CANONICAL_DRAFT_ANSWER,
    build_sheba_issue_draft_response,
    draft_has_settlement_bank_grounding,
    draft_has_settlement_grounding,
    has_valid_extracted_iban,
    is_commission_policy_question,
    is_policy_or_informational_question,
    is_settlement_account_operational_request,
    is_settlement_bank_policy_question,
    is_settlement_timing_policy_question,
    is_vague_commission_policy_draft,
    is_vague_settlement_bank_policy_draft,
    is_vague_settlement_policy_draft,
)
from app.operator_console.knowledge_hints import KnowledgeHint
from app.workflows.cancellation_request_detection import draft_asks_cancellation_reason
from app.workflows.operational_information_sufficiency import (
    _deterministic_scenario_acknowledgment,
    apply_operational_sufficiency_calibration,
    apply_panel_issue_draft_calibration,
    detect_unnecessary_detail_request,
    detect_unnecessary_shop_identifier_request,
    draft_requests_panel_or_shop_id,
    evaluate_operational_sufficiency,
    has_runtime_shop_identity_context,
    is_seller_panel_issue,
    operationally_complete_request,
)
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecision,
    ShipmentDeliveryDecisionType,
    shipment_delivery_reflection_metadata_row,
)

_SCENARIO_SHIPMENT = "shipment_reshipment"
_SCENARIO_CANCELLATION = "cancellation_request"
_SCENARIO_PRODUCT_APPROVAL = "product_approval"
_SHIPMENT_COMPLETE_ACK = "اطلاعات ارسال دریافت شد و در دست بررسی قرار گرفت."
_PRODUCT_REVIEW_ACK = "درخواست شما برای بررسی کالا ثبت شد و در دست بررسی قرار گرفت."

REFLECTION_PROVIDER_DISABLED = "disabled"
REFLECTION_PROVIDER_RULE_BASED = "rule_based"
REFLECTION_PROVIDER_OPENAI_HYBRID = "openai_hybrid"

_HIGH_CONFIDENCE = "high"
_MEDIUM_CONFIDENCE = "medium"

_ORDER_ID_ASK_MARKERS = (
    "شماره سفارش",
    "شناسه سفارش",
    "کد سفارش",
    "order id",
)
_TRACKING_ASK_MARKERS = (
    "کد رهگیری",
    "کد پیگیری",
    "نحوه ارسال",
    "روش ارسال",
    "شیوه ارسال",
)
_SHEBA_ASK_MARKERS = (
    "شماره شبا",
    "شماره شبای",
    "شبا را",
    "شبای",
    "iban",
)
_FORBIDDEN_WORDING_MARKERS = (
    "شناسه پنل",
    "کد پنل",
    "شناسه فروشگاه",
    "شناسه عکس",
    "کد عکس",
    "شناسه تصویر",
    "تماس بگیرید",
    "با ما تماس",
    "جزئیات بیشتری ارائه دهید",
    "جزئیات بیشتری درباره",
    "لطفاً جزئیات بیشتری",
    "لطفا جزئیات بیشتری",
)
_UNSUPPORTED_CLAIM_MARKERS = (
    "پنل شما فعال می‌شود",
    "پنل شما فعال میشود",
    "پنل فعال می‌شود",
    "پنل فعال میشود",
    "علت بسته شدن پنل",
)
_PHOTO_ASK_MARKERS = (
    "لطفاً عکس",
    "لطفا عکس",
    "لطفاً تصویر",
    "لطفا تصویر",
    "اسکرین‌شات",
    "اسکرین شات",
    "screenshot",
    "فایل عکس",
)


class ReflectionIssueType(StrEnum):
    UNNECESSARY_QUESTION = "unnecessary_question"
    REPEATED_IDENTIFIER_REQUEST = "repeated_identifier_request"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    POLICY_GROUNDING_FAILURE = "policy_grounding_failure"
    FORBIDDEN_WORDING = "forbidden_wording"
    OVER_QUESTIONING = "over_questioning"
    PANEL_IDENTIFIER_REQUEST = "panel_identifier_request"
    UNNECESSARY_IDENTIFIER_REQUEST = "unnecessary_identifier_request"
    PHOTO_REQUEST_NOT_NEEDED = "photo_request_not_needed"
    MISSING_OPERATIONAL_ACK = "missing_operational_ack"
    WEAK_POLICY_ANSWER = "weak_policy_answer"


@dataclass(frozen=True)
class ReflectionFinding:
    """Single operational issue detected in a final draft."""

    issue_type: ReflectionIssueType
    confidence: str
    summary: str


@dataclass(frozen=True)
class FinalDraftReflectionContext:
    """Inputs for final draft reflection (aggregate-safe only)."""

    seller_text: str
    detected_intent: str | None = None
    suggested_action: str | None = None
    conceptual_intent_fa: str | None = None
    draft_style: str | None = None
    order_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    tracking_code: str | None = None
    extracted_iban: str | None = None
    has_incomplete_iban_entity: bool = False
    entity_warnings_summary: str | None = None
    shop_id: str | None = None
    policy_hints: tuple[KnowledgeHint | Mapping[str, Any], ...] = ()
    draft_provider: str | None = None
    pending_request_type: str | None = None
    pending_request_fulfilled: bool = False
    tracking_optional: bool = False
    context_order_ids: tuple[str, ...] = ()
    context_product_ids: tuple[str, ...] = ()
    context_tracking_codes: tuple[str, ...] = ()
    context_ibans: tuple[str, ...] = ()
    runtime_shop_identity_available: bool = False
    runtime_shop_id_present: bool = False


@dataclass(frozen=True)
class FinalDraftReflectionResult:
    """Outcome of a single final-draft reflection pass (no loops)."""

    original_draft: str
    final_draft: str
    reviewed: bool
    findings: tuple[ReflectionFinding, ...] = ()
    rewrite_applied: bool = False
    openai_review_used: bool = False
    blocked_issue_count: int = 0
    rewrite_pass_count: int = 0
    latency_ms: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_order_ids(order_ids: Sequence[str]) -> bool:
    return any(str(value).strip() for value in order_ids)


def _has_product_ids(product_ids: Sequence[str]) -> bool:
    return any(str(value).strip() for value in product_ids)


def _has_tracking(tracking_code: str | None) -> bool:
    return bool(tracking_code and str(tracking_code).strip())


def _draft_asks_order_id(draft: str) -> bool:
    return _has_any(draft, _ORDER_ID_ASK_MARKERS)


def _draft_asks_tracking(draft: str) -> bool:
    return _has_any(draft, _TRACKING_ASK_MARKERS)


def _draft_asks_sheba(draft: str) -> bool:
    return _has_any(draft, _SHEBA_ASK_MARKERS)


def _draft_asks_photo(draft: str) -> bool:
    return _has_any(draft, _PHOTO_ASK_MARKERS) or draft_uses_forbidden_photo_id_wording(draft)


_GENERIC_CLARIFICATION_PHRASES = (
    "چه کمکی نیاز دارید",
    "چه کمکی نیاز دارین",
    "سوال خاصی دارید",
    "توضیحات بیشتری ارائه دهید",
    "جزئیات بیشتری ارائه دهید",
    "لطفاً مشخص کنید",
    "لطفا مشخص کنید",
    "چه درخواستی دارید",
    "چگونه می‌توانیم کمک کنیم",
    "چگونه میتونیم کمک کنیم",
    "لطفاً مشخص کنید چه",
    "مشخص کنید چه کمکی",
)

_PENDING_ACK_MARKERS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "requested_tracking_code": (
        "کد رهگیری دریافت شد",
        "رهگیری دریافت شد",
    ),
    "requested_order_id": ("شماره سفارش دریافت شد",),
    "requested_product_id": ("شناسه کالا دریافت شد",),
    "requested_sheba": ("شماره شبا دریافت شد",),
    "requested_photo_file": ("فایل عکس دریافت شد", "عکس دریافت شد"),
}


def draft_is_generic_clarification(draft: str) -> bool:
    """True when draft asks vague clarification instead of operational acknowledgment."""
    text = draft.strip()
    if not text:
        return False
    return _has_any(text, _GENERIC_CLARIFICATION_PHRASES)


def draft_has_pending_fulfillment_acknowledgment(draft: str, request_type: str | None) -> bool:
    """True when draft already contains the expected pending-fulfillment acknowledgment."""
    if not request_type:
        return False
    markers = _PENDING_ACK_MARKERS_BY_TYPE.get(request_type, ())
    if markers and _has_any(draft, markers):
        return True
    if request_type == "requested_tracking_code":
        return "رهگیری" in draft and "دریافت شد" in draft
    if request_type == "requested_order_id":
        return "سفارش" in draft and "دریافت شد" in draft
    if request_type == "requested_product_id":
        return "شناسه کالا" in draft and "دریافت شد" in draft
    if request_type == "requested_sheba":
        return "شبا" in draft and "دریافت شد" in draft
    return False


def should_rewrite_for_pending_fulfillment(
    draft: str,
    context: FinalDraftReflectionContext,
) -> bool:
    """True when a fulfilled pending admin request needs a deterministic acknowledgment."""
    if not context.pending_request_fulfilled or not context.pending_request_type:
        return False
    if draft_has_pending_fulfillment_acknowledgment(draft, context.pending_request_type):
        return False

    if draft_is_generic_clarification(draft) or detect_unnecessary_detail_request(draft):
        return True

    req_type = context.pending_request_type
    if req_type == "requested_tracking_code" and _draft_asks_tracking(draft):
        return True
    if req_type == "requested_order_id" and _draft_asks_order_id(draft):
        return True
    if req_type == "requested_sheba" and _draft_asks_sheba(draft):
        return True

    # Fulfilled pending request but draft is not the canonical acknowledgment.
    return True


def resolve_reflection_provider(settings: AppSettings | None = None) -> str:
    """Return effective reflection provider mode."""
    cfg = settings or get_settings()
    if not cfg.final_draft_reflection_enabled:
        return REFLECTION_PROVIDER_DISABLED
    raw = (cfg.final_draft_reflection_provider or REFLECTION_PROVIDER_RULE_BASED).strip().lower()
    if raw in {
        REFLECTION_PROVIDER_DISABLED,
        REFLECTION_PROVIDER_RULE_BASED,
        REFLECTION_PROVIDER_OPENAI_HYBRID,
    }:
        return raw
    return REFLECTION_PROVIDER_RULE_BASED


def run_deterministic_reflection_checks(
    draft: str,
    context: FinalDraftReflectionContext,
) -> list[ReflectionFinding]:
    """Rule-based operational checks on the final draft."""
    text = draft.strip()
    if not text:
        return []

    findings: list[ReflectionFinding] = []
    seller = context.seller_text
    merged_order_ids = tuple(
        dict.fromkeys([*context.order_ids, *context.context_order_ids]),
    )
    merged_product_ids = tuple(
        dict.fromkeys([*context.product_ids, *context.context_product_ids]),
    )
    merged_tracking = context.tracking_code
    if not merged_tracking and context.context_tracking_codes:
        merged_tracking = context.context_tracking_codes[-1]
    merged_iban = context.extracted_iban
    if not merged_iban and context.context_ibans:
        merged_iban = context.context_ibans[-1]
    policy_or_info_question = is_policy_or_informational_question(
        seller,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    )

    if _has_order_ids(merged_order_ids) and _draft_asks_order_id(text):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST,
                confidence=_HIGH_CONFIDENCE,
                summary="order_id already extracted",
            ),
        )

    if _has_tracking(merged_tracking) and _draft_asks_tracking(text):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST,
                confidence=_HIGH_CONFIDENCE,
                summary="tracking_code already extracted",
            ),
        )

    if has_valid_extracted_iban(merged_iban, seller) and _draft_asks_sheba(text):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST,
                confidence=_HIGH_CONFIDENCE,
                summary="sheba already extracted",
            ),
        )

    if detect_unnecessary_detail_request(text):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.UNNECESSARY_QUESTION,
                confidence=_HIGH_CONFIDENCE,
                summary="generic detail request",
            ),
        )

    sufficiency = evaluate_operational_sufficiency(
        seller_text=seller,
        detected_intent=context.detected_intent,
        suggested_action=context.suggested_action,
        order_ids=context.order_ids,
        product_ids=context.product_ids,
        tracking_code=context.tracking_code,
        conceptual_intent_fa=context.conceptual_intent_fa,
        draft=text,
    )
    if sufficiency.over_questioning or sufficiency.unnecessary_clarification:
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.OVER_QUESTIONING,
                confidence=_HIGH_CONFIDENCE,
                summary="over-questioning vs operational policy",
            ),
        )

    if (
        sufficiency.policy.scenario == _SCENARIO_CANCELLATION
        and sufficiency.policy.operationally_complete_request
        and (draft_asks_cancellation_reason(text) or detect_unnecessary_detail_request(text))
    ):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.OVER_QUESTIONING,
                confidence=_HIGH_CONFIDENCE,
                summary="cancellation request must not ask reason or extra details",
            ),
        )
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.UNNECESSARY_QUESTION,
                confidence=_HIGH_CONFIDENCE,
                summary="cancellation reason/detail request",
            ),
        )
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.MISSING_OPERATIONAL_ACK,
                confidence=_HIGH_CONFIDENCE,
                summary="cancellation acknowledgment expected",
            ),
        )

    if _has_any(text, _FORBIDDEN_WORDING_MARKERS):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.FORBIDDEN_WORDING,
                confidence=_HIGH_CONFIDENCE,
                summary="forbidden support wording",
            ),
        )

    if is_seller_panel_issue(
        seller,
        detected_intent=context.detected_intent,
        suggested_action=context.suggested_action,
        conceptual_intent_fa=context.conceptual_intent_fa,
        order_ids=context.order_ids,
        product_ids=context.product_ids,
    ) and (draft_requests_panel_or_shop_id(text) or _has_any(text, _FORBIDDEN_WORDING_MARKERS[:3])):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.PANEL_IDENTIFIER_REQUEST,
                confidence=_HIGH_CONFIDENCE,
                summary="panel issue must not ask panel/shop id",
            ),
        )

    runtime_shop_identity = (
        context.runtime_shop_identity_available
        or has_runtime_shop_identity_context(shop_id=context.shop_id)
    )
    if detect_unnecessary_shop_identifier_request(
        text,
        runtime_shop_identity_available=runtime_shop_identity,
        shop_id=context.shop_id,
    ):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.UNNECESSARY_IDENTIFIER_REQUEST,
                confidence=_HIGH_CONFIDENCE,
                summary="runtime shop identity already available",
            ),
        )

    if _has_any(text, _UNSUPPORTED_CLAIM_MARKERS):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.UNSUPPORTED_CLAIM,
                confidence=_HIGH_CONFIDENCE,
                summary="unsupported panel claim",
            ),
        )

    if _draft_asks_photo(text) and not should_request_photo_file(
        seller,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.PHOTO_REQUEST_NOT_NEEDED,
                confidence=_HIGH_CONFIDENCE,
                summary="unnecessary photo/screenshot request",
            ),
        )

    if is_settlement_bank_policy_question(
        seller,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ):
        if is_vague_settlement_bank_policy_draft(text) or not draft_has_settlement_bank_grounding(
            text,
        ):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.POLICY_GROUNDING_FAILURE,
                    confidence=_HIGH_CONFIDENCE,
                    summary="settlement bank policy answer not grounded",
                ),
            )
        elif _draft_asks_sheba(text):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.POLICY_GROUNDING_FAILURE,
                    confidence=_HIGH_CONFIDENCE,
                    summary="settlement bank policy must not request Sheba",
                ),
            )
    elif is_settlement_timing_policy_question(
        seller,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ):
        if is_vague_settlement_policy_draft(text) or not draft_has_settlement_grounding(text):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.POLICY_GROUNDING_FAILURE,
                    confidence=_HIGH_CONFIDENCE,
                    summary="settlement answer not grounded",
                ),
            )
        elif _has_any(text, ("بستگی دارد", "به قوانین", "راهنما", "مراجعه کنید")):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.WEAK_POLICY_ANSWER,
                    confidence=_HIGH_CONFIDENCE,
                    summary="vague settlement policy wording",
                ),
            )

    if is_commission_policy_question(
        seller,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ) and is_vague_commission_policy_draft(text):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.WEAK_POLICY_ANSWER,
                confidence=_HIGH_CONFIDENCE,
                summary="commission policy answer too vague",
            ),
        )

    if context.pending_request_fulfilled and (
        _draft_asks_order_id(text)
        or _draft_asks_tracking(text)
        or _draft_asks_sheba(text)
        or detect_unnecessary_detail_request(text)
        or draft_is_generic_clarification(text)
        or should_rewrite_for_pending_fulfillment(text, context)
    ):
        if _draft_asks_order_id(text) or _draft_asks_tracking(text) or _draft_asks_sheba(text):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST,
                    confidence=_HIGH_CONFIDENCE,
                    summary="seller fulfilled pending admin request",
                ),
            )
        if draft_is_generic_clarification(text) or detect_unnecessary_detail_request(text):
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.OVER_QUESTIONING,
                    confidence=_HIGH_CONFIDENCE,
                    summary="generic clarification after fulfilled pending request",
                ),
            )
            findings.append(
                ReflectionFinding(
                    issue_type=ReflectionIssueType.UNNECESSARY_QUESTION,
                    confidence=_HIGH_CONFIDENCE,
                    summary="generic clarification after fulfilled pending request",
                ),
            )
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.MISSING_OPERATIONAL_ACK,
                confidence=_HIGH_CONFIDENCE,
                summary="should acknowledge fulfilled pending request",
            ),
        )

    if (
        not policy_or_info_question
        and operationally_complete_request(
            seller_text=seller,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            order_ids=merged_order_ids,
            product_ids=merged_product_ids,
            tracking_code=merged_tracking,
            conceptual_intent_fa=context.conceptual_intent_fa,
        )
        and (
            _draft_asks_order_id(text)
            or _draft_asks_tracking(text)
            or detect_unnecessary_detail_request(text)
            or "؟" in text
        )
    ):
        findings.append(
            ReflectionFinding(
                issue_type=ReflectionIssueType.MISSING_OPERATIONAL_ACK,
                confidence=_HIGH_CONFIDENCE,
                summary="should acknowledge not re-ask",
            ),
        )

    return findings


def _high_confidence_issue_types(findings: Sequence[ReflectionFinding]) -> set[ReflectionIssueType]:
    return {item.issue_type for item in findings if item.confidence == _HIGH_CONFIDENCE}


def _draft_needs_operational_ack(draft: str) -> bool:
    return (
        _draft_asks_order_id(draft)
        or _draft_asks_tracking(draft)
        or _draft_asks_sheba(draft)
        or detect_unnecessary_detail_request(draft)
        or _has_any(draft, _FORBIDDEN_WORDING_MARKERS)
    )


def _scenario_complete_acknowledgment(
    policy: Any,
    *,
    product_ids: Sequence[str],
) -> str | None:
    ack = _deterministic_scenario_acknowledgment(policy)
    if ack:
        return ack
    if policy.scenario == _SCENARIO_SHIPMENT and policy.operationally_complete_request:
        return _SHIPMENT_COMPLETE_ACK
    if policy.scenario == _SCENARIO_PRODUCT_APPROVAL and _has_product_ids(product_ids):
        return _PRODUCT_REVIEW_ACK
    return None


def _apply_operational_ack_rewrite(draft: str, context: FinalDraftReflectionContext) -> str:
    sufficiency = evaluate_operational_sufficiency(
        seller_text=context.seller_text,
        detected_intent=context.detected_intent,
        suggested_action=context.suggested_action,
        order_ids=context.order_ids,
        product_ids=context.product_ids,
        tracking_code=context.tracking_code,
        conceptual_intent_fa=context.conceptual_intent_fa,
        draft=draft,
    )
    policy = sufficiency.policy
    if not policy.operationally_complete_request:
        calibrated, _ = apply_operational_sufficiency_calibration(
            draft,
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            order_ids=context.order_ids,
            product_ids=context.product_ids,
            tracking_code=context.tracking_code,
            conceptual_intent_fa=context.conceptual_intent_fa,
            shop_id=context.shop_id,
        )
        return calibrated if calibrated.strip() and calibrated != draft.strip() else draft.strip()

    if not _draft_needs_operational_ack(draft):
        return draft.strip()

    ack = _scenario_complete_acknowledgment(policy, product_ids=context.product_ids)
    if ack:
        return ack
    return draft.strip()


def _strip_identifier_request_sentences(
    draft: str,
    *,
    strip_order: bool = False,
    strip_tracking: bool = False,
    strip_sheba: bool = False,
    strip_detail: bool = False,
) -> str:
    from app.evals.draft_style import _SENTENCE_SPLIT_RE

    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(draft.strip()) if part.strip()]
    kept: list[str] = []
    for sentence in sentences:
        drop = False
        if strip_order and _draft_asks_order_id(sentence):
            drop = True
        if strip_tracking and _draft_asks_tracking(sentence):
            drop = True
        if strip_sheba and _draft_asks_sheba(sentence):
            drop = True
        if strip_detail and detect_unnecessary_detail_request(sentence):
            drop = True
        if not drop:
            kept.append(sentence)
    if not kept:
        return ""
    joined = ". ".join(kept)
    if not joined.endswith((".", "؟", "!")):
        joined += "."
    return joined


def apply_reflection_rewrites(
    draft: str,
    context: FinalDraftReflectionContext,
    findings: Sequence[ReflectionFinding],
    *,
    max_chars: int = 700,
) -> tuple[str, bool]:
    """Apply at most one minimal rewrite pass for high-confidence issues."""
    issue_types = _high_confidence_issue_types(findings)
    if not issue_types:
        return draft.strip(), False

    result = draft.strip()
    changed = False
    policy_or_info_question = is_policy_or_informational_question(
        context.seller_text,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    )

    if ReflectionIssueType.PANEL_IDENTIFIER_REQUEST in issue_types or (
        ReflectionIssueType.UNSUPPORTED_CLAIM in issue_types
        and is_seller_panel_issue(
            context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            conceptual_intent_fa=context.conceptual_intent_fa,
        )
    ):
        rewritten, _metrics = apply_panel_issue_draft_calibration(
            result,
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            conceptual_intent_fa=context.conceptual_intent_fa,
            order_ids=context.order_ids,
            product_ids=context.product_ids,
            shop_id=context.shop_id,
        )
        if rewritten != result:
            result = rewritten
            changed = True

    if ReflectionIssueType.PHOTO_REQUEST_NOT_NEEDED in issue_types:
        rewritten, photo_changed, _ = calibrate_photo_evidence_wording(
            result,
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            conceptual_intent_fa=context.conceptual_intent_fa,
            suggested_action=context.suggested_action,
            product_ids=context.product_ids,
            extracted_iban=context.extracted_iban,
            has_incomplete_iban_entity=context.has_incomplete_iban_entity,
            entity_warnings_summary=context.entity_warnings_summary,
        )
        if photo_changed:
            result = rewritten
            changed = True

    if (
        ReflectionIssueType.POLICY_GROUNDING_FAILURE in issue_types
        or ReflectionIssueType.WEAK_POLICY_ANSWER in issue_types
    ):
        if is_commission_policy_question(
            context.seller_text,
            detected_intent=context.detected_intent,
            conceptual_intent_fa=context.conceptual_intent_fa,
            suggested_action=context.suggested_action,
        ):
            replacement = (
                COMMISSION_POLICY_FALLBACK_DRAFT_ANSWER
                if is_vague_commission_policy_draft(result)
                else result
            )
        elif is_settlement_bank_policy_question(
            context.seller_text,
            detected_intent=context.detected_intent,
            conceptual_intent_fa=context.conceptual_intent_fa,
            suggested_action=context.suggested_action,
        ):
            replacement = SETTLEMENT_BANK_CANONICAL_DRAFT_ANSWER
        elif is_settlement_account_operational_request(
            context.seller_text,
            detected_intent=context.detected_intent,
            conceptual_intent_fa=context.conceptual_intent_fa,
            suggested_action=context.suggested_action,
        ):
            replacement = build_sheba_issue_draft_response(
                context.seller_text,
                extracted_iban=context.extracted_iban,
                has_incomplete_iban_entity=context.has_incomplete_iban_entity,
                entity_warnings_summary=context.entity_warnings_summary,
            )
        elif is_settlement_timing_policy_question(
            context.seller_text,
            detected_intent=context.detected_intent,
            conceptual_intent_fa=context.conceptual_intent_fa,
            suggested_action=context.suggested_action,
        ):
            replacement = SETTLEMENT_CANONICAL_DRAFT_ANSWER
        else:
            grounding = apply_policy_grounding_calibration(
                result,
                seller_text=context.seller_text,
                detected_intent=context.detected_intent,
                suggested_action=context.suggested_action,
                draft_style=context.draft_style or DRAFT_STYLE_POLICY_EXPLANATION,
                hints=context.policy_hints,
                conceptual_intent_fa=context.conceptual_intent_fa,
                extracted_iban=context.extracted_iban,
                has_incomplete_iban_entity=context.has_incomplete_iban_entity,
                entity_warnings_summary=context.entity_warnings_summary,
            )
            replacement = grounding.draft_reply
        if replacement != result:
            result = replacement
            changed = True

    if ReflectionIssueType.MISSING_OPERATIONAL_ACK in issue_types:
        if policy_or_info_question:
            ack = result.strip()
        else:
            ack = _apply_operational_ack_rewrite(result, context)
        if ack != result:
            result = ack
            changed = True

    if ReflectionIssueType.UNNECESSARY_IDENTIFIER_REQUEST in issue_types:
        runtime_shop_identity = (
            context.runtime_shop_identity_available
            or has_runtime_shop_identity_context(shop_id=context.shop_id)
        )
        if runtime_shop_identity and operationally_complete_request(
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            order_ids=context.order_ids,
            product_ids=context.product_ids,
            tracking_code=context.tracking_code,
            conceptual_intent_fa=context.conceptual_intent_fa,
        ):
            result = "درخواست شما ثبت شد و در دست بررسی قرار گرفت."
            changed = True

    if ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST in issue_types:
        stripped = _strip_identifier_request_sentences(
            result,
            strip_order=_has_order_ids(context.order_ids) and _draft_asks_order_id(result),
            strip_tracking=_has_tracking(context.tracking_code) and _draft_asks_tracking(result),
            strip_sheba=has_valid_extracted_iban(context.extracted_iban, context.seller_text)
            and _draft_asks_sheba(result),
            strip_detail=True,
        )
        if stripped != result:
            result = stripped
            changed = True
        if not result.strip() or _draft_needs_operational_ack(result):
            ack = _apply_operational_ack_rewrite(
                result if result.strip() else draft,
                context,
            )
            if ack.strip() and ack != result:
                result = ack
                changed = True

    if (
        ReflectionIssueType.UNNECESSARY_QUESTION in issue_types
        or ReflectionIssueType.OVER_QUESTIONING in issue_types
        or ReflectionIssueType.FORBIDDEN_WORDING in issue_types
    ):
        if policy_or_info_question:
            calibrated = result.strip()
        else:
            calibrated, _sufficiency = apply_operational_sufficiency_calibration(
                result,
                seller_text=context.seller_text,
                detected_intent=context.detected_intent,
                suggested_action=context.suggested_action,
                order_ids=context.order_ids,
                product_ids=context.product_ids,
                tracking_code=context.tracking_code,
                conceptual_intent_fa=context.conceptual_intent_fa,
                shop_id=context.shop_id,
            )
        if calibrated != result:
            result = calibrated
            changed = True

    result, product_changed = apply_product_wording_calibration(
        result,
        seller_text=context.seller_text,
        detected_intent=context.detected_intent,
        suggested_action=context.suggested_action,
        conceptual_intent_fa=context.conceptual_intent_fa,
        draft_style=context.draft_style,
        product_ids=context.product_ids,
    )
    if product_changed.product_wording_normalized:
        result = product_changed.calibrated_draft
        changed = True

    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip() + "…"
        changed = True

    final = result.strip()
    return final, changed and final != draft.strip()


def _parse_openai_reflection_json(content: str) -> list[ReflectionFinding]:
    """Parse compact reviewer JSON; never expose raw reasoning."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    issues = payload.get("issues")
    if not isinstance(issues, list):
        return []
    parsed: list[ReflectionFinding] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        raw_type = str(item.get("type") or "").strip()
        try:
            issue_type = ReflectionIssueType(raw_type)
        except ValueError:
            continue
        confidence = str(item.get("confidence") or _MEDIUM_CONFIDENCE).strip().lower()
        if confidence not in {_HIGH_CONFIDENCE, _MEDIUM_CONFIDENCE}:
            confidence = _MEDIUM_CONFIDENCE
        summary = str(item.get("summary") or "")[:120]
        parsed.append(
            ReflectionFinding(
                issue_type=issue_type,
                confidence=confidence,
                summary=summary or issue_type.value,
            ),
        )
    return parsed


def _openai_reflection_review(
    draft: str,
    context: FinalDraftReflectionContext,
    *,
    settings: AppSettings | None = None,
    review_fn: Any | None = None,
) -> list[ReflectionFinding]:
    """Optional compact OpenAI reviewer for uncertain cases only."""
    cfg = settings or get_settings()
    api_key = __import__("os").environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and review_fn is None:
        return []

    model = (cfg.final_draft_reflection_openai_model or "gpt-4o-mini").strip()
    prompt = (
        "Review this Persian vendor-support draft for operational mistakes only. "
        "Return JSON only: "
        '{"issues":[{"type":"issue_type","confidence":"high|medium","summary":"short"}]}. '
        "Allowed types: unnecessary_question, repeated_identifier_request, "
        "unsupported_claim, policy_grounding_failure, forbidden_wording, over_questioning, "
        "panel_identifier_request, photo_request_not_needed, missing_operational_ack, "
        "weak_policy_answer. "
        "No chain-of-thought. No rewrite.\n"
        f"seller_text={context.seller_text[:400]}\n"
        f"draft={draft[:500]}"
    )

    if review_fn is not None:
        raw = review_fn(prompt, model=model)
    else:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=120,
        )
        raw = response.choices[0].message.content if response.choices else ""
    if not isinstance(raw, str):
        return []
    return _parse_openai_reflection_json(raw)


def review_final_draft(
    draft: str,
    context: FinalDraftReflectionContext,
    *,
    settings: AppSettings | None = None,
    review_fn: Any | None = None,
) -> FinalDraftReflectionResult:
    """Run a single reflection review pass (deterministic; optional OpenAI supplement)."""
    import time

    started = time.perf_counter()
    original = (draft or "").strip()
    provider_mode = resolve_reflection_provider(settings)
    if provider_mode == REFLECTION_PROVIDER_DISABLED or not original:
        return FinalDraftReflectionResult(
            original_draft=original,
            final_draft=original,
            reviewed=False,
        )

    findings = run_deterministic_reflection_checks(original, context)
    openai_used = False
    uncertain = [f for f in findings if f.confidence == _MEDIUM_CONFIDENCE]
    if (
        provider_mode == REFLECTION_PROVIDER_OPENAI_HYBRID
        and uncertain
        and (context.draft_provider or "").strip().lower() == "openai"
    ):
        extra = _openai_reflection_review(
            original,
            context,
            settings=settings,
            review_fn=review_fn,
        )
        if extra:
            openai_used = True
            merged = {f.issue_type: f for f in findings}
            for item in extra:
                if item.confidence == _HIGH_CONFIDENCE:
                    merged[item.issue_type] = item
            findings = list(merged.values())

    rewrite_applied = False
    rewrite_pass_count = 0
    final = original

    if should_rewrite_for_pending_fulfillment(original, context):
        from app.workflows.multi_turn_ticket_context import pending_fulfillment_ack_for_type

        ack = pending_fulfillment_ack_for_type(
            context.pending_request_type,
            tracking_optional=context.tracking_optional,
        )
        if ack:
            final = ack
            rewrite_applied = True
            rewrite_pass_count = 1

    if not rewrite_applied and findings:
        rewritten, changed = apply_reflection_rewrites(
            original,
            context,
            findings,
            max_chars=(settings or get_settings()).final_draft_reflection_max_rewrite_chars,
        )
        final = rewritten
        rewrite_applied = changed
        if changed:
            rewrite_pass_count = 1

    blocked = sum(1 for item in findings if item.confidence == _HIGH_CONFIDENCE)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return FinalDraftReflectionResult(
        original_draft=original,
        final_draft=final,
        reviewed=True,
        findings=tuple(findings),
        rewrite_applied=rewrite_applied,
        openai_review_used=openai_used,
        blocked_issue_count=blocked,
        rewrite_pass_count=rewrite_pass_count,
        latency_ms=elapsed_ms,
    )


def apply_final_draft_reflection_review(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    draft_style: str | None = None,
    order_ids: Sequence[str] = (),
    product_ids: Sequence[str] = (),
    tracking_code: str | None = None,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
    shop_id: str | None = None,
    policy_hints: Sequence[KnowledgeHint | Mapping[str, Any]] = (),
    draft_provider: str | None = None,
    pending_request_type: str | None = None,
    pending_request_fulfilled: bool = False,
    tracking_optional: bool = False,
    context_order_ids: Sequence[str] = (),
    context_product_ids: Sequence[str] = (),
    context_tracking_codes: Sequence[str] = (),
    context_ibans: Sequence[str] = (),
    runtime_shop_identity_available: bool = False,
    runtime_shop_id_present: bool = False,
    settings: AppSettings | None = None,
    review_fn: Any | None = None,
    shipment_delivery_decision: ShipmentDeliveryDecision | None = None,
) -> tuple[str, FinalDraftReflectionResult]:
    """Review and optionally rewrite the final draft once."""
    protected_reply: str | None = None
    if shipment_delivery_decision and shipment_delivery_decision.should_override_draft:
        protected_reply = (shipment_delivery_decision.recommended_reply_fa or "").strip() or None
        if protected_reply:
            draft = protected_reply

    context = FinalDraftReflectionContext(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        draft_style=draft_style,
        order_ids=tuple(order_ids),
        product_ids=tuple(product_ids),
        tracking_code=tracking_code,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
        shop_id=shop_id,
        policy_hints=tuple(policy_hints),
        draft_provider=draft_provider,
        pending_request_type=pending_request_type,
        pending_request_fulfilled=pending_request_fulfilled,
        tracking_optional=tracking_optional,
        context_order_ids=tuple(context_order_ids),
        context_product_ids=tuple(context_product_ids),
        context_tracking_codes=tuple(context_tracking_codes),
        context_ibans=tuple(context_ibans),
        runtime_shop_identity_available=runtime_shop_identity_available,
        runtime_shop_id_present=runtime_shop_id_present,
    )
    result = review_final_draft(
        draft,
        context,
        settings=settings,
        review_fn=review_fn,
    )
    result = FinalDraftReflectionResult(
        original_draft=result.original_draft,
        final_draft=result.final_draft,
        reviewed=result.reviewed,
        findings=result.findings,
        rewrite_applied=result.rewrite_applied,
        blocked_issue_count=result.blocked_issue_count,
        openai_review_used=result.openai_review_used,
        rewrite_pass_count=result.rewrite_pass_count,
        latency_ms=result.latency_ms,
        extra={
            **dict(result.extra),
            "reflection_runtime_shop_identity_available": (context.runtime_shop_identity_available),
            "reflection_runtime_shop_id_present": context.runtime_shop_id_present,
            "reflection_unnecessary_identifier_detected": any(
                finding.issue_type == ReflectionIssueType.UNNECESSARY_IDENTIFIER_REQUEST
                for finding in result.findings
            ),
        },
    )
    final_text = result.final_draft
    if protected_reply and _should_preserve_shipment_decision_reply(
        shipment_delivery_decision,
        protected_reply=protected_reply,
        reflected=final_text,
    ):
        final_text = protected_reply
        result = FinalDraftReflectionResult(
            original_draft=result.original_draft,
            final_draft=protected_reply,
            reviewed=result.reviewed,
            findings=result.findings,
            rewrite_applied=result.rewrite_applied,
            blocked_issue_count=result.blocked_issue_count,
            openai_review_used=result.openai_review_used,
            rewrite_pass_count=result.rewrite_pass_count,
            latency_ms=result.latency_ms,
            extra={
                **dict(result.extra),
                **shipment_delivery_reflection_metadata_row(shipment_delivery_decision),
            },
        )
    return final_text, result


_PROTECTED_SHIPMENT_DECISION_TYPES = frozenset(
    {
        ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND,
        ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID,
        ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_INVALID,
        ShipmentDeliveryDecisionType.NON_IRAN_POST_TRACKING_PRESENT,
        ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED,
        ShipmentDeliveryDecisionType.SELLER_REPLY_NO_POST_TRACKING_ACK,
        ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_VALID,
        ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID,
        ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK,
        ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK,
        ShipmentDeliveryDecisionType.INSUFFICIENT_ORDER_IDENTIFIER,
        ShipmentDeliveryDecisionType.ORDER_LOOKUP_FAILED,
        ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_IRAN_POST_TRACKING_ACK,
    },
)


def _should_preserve_shipment_decision_reply(
    decision: ShipmentDeliveryDecision | None,
    *,
    protected_reply: str,
    reflected: str,
) -> bool:
    if decision is None:
        return False
    if decision.decision_type not in _PROTECTED_SHIPMENT_DECISION_TYPES:
        return False
    return reflected.strip() != protected_reply.strip()


def reflection_metadata_row(result: FinalDraftReflectionResult) -> dict[str, Any]:
    """Safe aggregate metadata for graph state / preview (no hidden reasoning)."""
    issue_types = [item.issue_type.value for item in result.findings]
    return {
        "reflection_reviewed": result.reviewed,
        "reflection_issue_detected": bool(result.findings),
        "reflection_issue_types": issue_types,
        "reflection_rewrite_applied": result.rewrite_applied,
        "reflection_rewrite_rate": 1.0 if result.rewrite_applied else 0.0,
        "reflection_blocked_issue_count": result.blocked_issue_count,
        "reflection_openai_review_used": result.openai_review_used,
        "reflection_rewrite_pass_count": result.rewrite_pass_count,
        "reflection_latency_ms": result.latency_ms,
        "reflection_runtime_shop_identity_available": result.extra.get(
            "reflection_runtime_shop_identity_available",
        ),
        "reflection_runtime_shop_id_present": result.extra.get(
            "reflection_runtime_shop_id_present",
        ),
        "reflection_unnecessary_identifier_detected": result.extra.get(
            "reflection_unnecessary_identifier_detected",
        ),
    }


_REFLECTION_COMPARISON_FORBIDDEN_KEYS = frozenset(
    {
        "reasoning",
        "chain_of_thought",
        "reviewer_output",
        "openai_raw_output",
        "raw_prompt",
        "retrieval_results",
        "raw_snippets",
        "hidden_reasoning",
        "reviewer_thoughts",
    },
)


def reflection_comparison_session_row(
    *,
    raw_generated_draft: str,
    pre_reflection_draft: str,
    final_reflected_draft: str,
    result: FinalDraftReflectionResult,
    reflection_enabled: bool | None = None,
    reflection_provider: str | None = None,
) -> dict[str, Any]:
    """Session-only before/after drafts plus safe reflection labels (operator console)."""
    cfg = get_settings()
    enabled = (
        reflection_enabled if reflection_enabled is not None else cfg.final_draft_reflection_enabled
    )
    provider = (reflection_provider or resolve_reflection_provider(cfg)).strip()
    row = {
        "raw_generated_draft": (raw_generated_draft or "").strip(),
        "pre_reflection_draft": (pre_reflection_draft or "").strip(),
        "final_reflected_draft": (final_reflected_draft or "").strip(),
        "reflection_enabled": enabled,
        "reflection_provider": provider,
        **reflection_metadata_row(result),
    }
    assert_reflection_comparison_session_safe(row)
    return row


def assert_reflection_comparison_session_safe(row: Mapping[str, Any]) -> None:
    """Fail closed if reflection comparison leaks forbidden reviewer/prompt fields."""
    for key in _collect_reflection_comparison_keys(row):
        lowered = key.lower()
        if lowered in _REFLECTION_COMPARISON_FORBIDDEN_KEYS:
            raise ValueError(f"reflection comparison must not contain forbidden key: {key}")
        for token in (
            "chain_of_thought",
            "chain-of-thought",
            "hidden_reasoning",
            "reviewer_thought",
        ):
            if token in lowered:
                raise ValueError(f"reflection comparison must not contain forbidden key: {key}")
    for text in _iter_reflection_comparison_strings(row):
        lowered = text.lower()
        for token in ("chain of thought", "reviewer thoughts", "hidden reasoning"):
            if token in lowered:
                raise ValueError("reflection comparison must not contain forbidden reasoning text")


def _collect_reflection_comparison_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            keys.add(str(key))
            keys |= _collect_reflection_comparison_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _collect_reflection_comparison_keys(item)
    return keys


def _iter_reflection_comparison_strings(obj: Any) -> list[str]:
    values: list[str] = []
    if isinstance(obj, str):
        values.append(obj)
    elif isinstance(obj, Mapping):
        for value in obj.values():
            values.extend(_iter_reflection_comparison_strings(value))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_iter_reflection_comparison_strings(item))
    return values


def assert_reflection_single_pass(result: FinalDraftReflectionResult) -> None:
    """Guardrail: reflection must never loop."""
    if result.rewrite_pass_count > 1:
        raise ValueError("final draft reflection exceeded single rewrite pass")
