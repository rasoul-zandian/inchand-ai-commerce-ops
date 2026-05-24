"""Deterministic Persian operational drafts for mock agentic sandbox runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.evals.actionability_validation import (
    ActionabilityValidationResult,
    build_missing_identifier_request,
    validate_actionability,
)
from app.evals.draft_evidence_wording_calibration import (
    BRAND_NAME_REQUEST,
    DEFAULT_PHOTO_FILE_REQUEST,
    GENERIC_REVIEW_ACK,
    PRODUCT_ID_REQUEST,
    PRODUCT_REVIEW_ACK,
    should_request_photo_file,
)
from app.evals.offline_draft_generation import assert_draft_reply_safe
from app.knowledge.policy_fact_extraction import (
    SETTLEMENT_CANONICAL_DRAFT_ANSWER,
    build_sheba_issue_draft_response,
    is_settlement_account_operational_request,
    is_settlement_timing_policy_question,
)
from app.workflows.operational_information_sufficiency import (
    detect_operational_scenario,
    is_delivery_completed_seller_message,
    is_shipment_seller_message,
    minimum_required_operational_entities,
    resolve_operational_order_ids,
)

_SCENARIO_PRODUCT_APPROVAL = "product_approval"

MOCK_OPERATIONAL_DRAFT_MAX_CHARS = 300

_SCENARIO_CANCELLATION = "cancellation_request"
_SCENARIO_DELIVERY_COMPLETED = "delivery_completed"
_SCENARIO_SHIPMENT = "shipment_reshipment"


@dataclass(frozen=True)
class MockOperationalDraftInput:
    """Structured graph fields used to build a mock operational draft."""

    detected_intent: str | None = None
    conceptual_intent_fa: str | None = None
    suggested_action: str | None = None
    suggested_action_reason: str | None = None
    seller_text: str = ""
    order_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    tracking_code: str | None = None
    iban_masked: str | None = None
    extracted_iban: str | None = None
    has_incomplete_iban_entity: bool = False
    entity_warnings_summary: str | None = None
    actionability: Mapping[str, Any] | None = None


def _normalize_token(value: str | None) -> str:
    return (value or "").strip().lower()


def _parse_missing_entities(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    parts = [part.strip() for part in str(raw).replace(",", " ").split()]
    return tuple(part for part in parts if part)


def _actionability_validation(
    inputs: MockOperationalDraftInput,
) -> ActionabilityValidationResult:
    if inputs.actionability:
        missing = _parse_missing_entities(
            str(inputs.actionability.get("actionability_missing_entities") or ""),
        )
        actionable = inputs.actionability.get("actionability_actionable")
        should_request = inputs.actionability.get("requires_identifier_request")
        if should_request is None:
            should_request = bool(missing) or actionable is False
        return ActionabilityValidationResult(
            actionable=bool(actionable) if actionable is not None else not missing,
            missing_required_entities=missing,
            requested_action=str(
                inputs.actionability.get("requested_action") or inputs.suggested_action or "",
            ),
            validation_reason=str(
                inputs.actionability.get("actionability_validation_reason") or "mock",
            ),
            should_request_identifier=bool(should_request),
        )

    return validate_actionability(
        suggested_action=inputs.suggested_action or "",
        seller_text=inputs.seller_text,
        detected_intent=inputs.detected_intent,
        order_ids=list(inputs.order_ids),
        product_ids=list(inputs.product_ids),
        tracking_code=inputs.tracking_code,
    )


def _truncate_mock_draft(text: str, *, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _policy_answer_template(
    *,
    action: str,
    intent: str,
    seller_text: str,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> str | None:
    if is_settlement_account_operational_request(
        seller_text,
        detected_intent=intent,
        suggested_action=action,
    ):
        return build_sheba_issue_draft_response(
            seller_text,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
    if is_settlement_timing_policy_question(
        seller_text,
        detected_intent=intent,
        suggested_action=action,
    ):
        return SETTLEMENT_CANONICAL_DRAFT_ANSWER
    if "publish" in intent or "publishing" in intent or "تأیید کالا" in seller_text:
        return (
            "برای انتشار کالا، عنوان، توضیحات، قیمت و تصاویر باید مطابق قوانین "
            "انتشار محصول باشد. کالاهای ممنوعه یا دارای محتوای ناقص تأیید نمی‌شوند."
        )
    if "prohibited" in intent or "ممنوع" in seller_text:
        return (
            "فهرست کالاهای ممنوعه در راهنمای فروشندگان مشخص شده است. "
            "اگر کالا در این فهرست باشد، امکان انتشار یا فروش آن وجود ندارد."
        )
    if action == "answer_policy_question" or "policy" in intent:
        return (
            "پاسخ شما بر اساس قوانین و راهنمای مرتبط با درخواست‌تان به‌صورت شفاف "
            "در همین پیام ارائه می‌شود."
        )
    return None


def _template_for_operational_case(
    *,
    suggested_action: str,
    detected_intent: str,
    seller_text: str,
    order_ids: Sequence[str],
    product_ids: Sequence[str],
    tracking_code: str | None = None,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> str:
    action = _normalize_token(suggested_action)
    intent = _normalize_token(detected_intent)

    scenario = detect_operational_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    )
    effective_orders = resolve_operational_order_ids(
        seller_text,
        tuple(order_ids),
        scenario=scenario,
    )
    missing = minimum_required_operational_entities(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=effective_orders,
        tracking_code=tracking_code,
    )

    if scenario == _SCENARIO_CANCELLATION:
        if missing:
            return "لطفاً شماره سفارش را ارسال کنید تا درخواست لغو بررسی شود."
        return "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."

    if scenario == _SCENARIO_DELIVERY_COMPLETED:
        if missing:
            return "لطفاً شماره سفارش را ارسال کنید تا درخواست تحویل بررسی شود."
        return "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."

    if scenario == _SCENARIO_SHIPMENT:
        if missing == ("order_id",):
            return "لطفاً شماره سفارش را ارسال کنید تا اطلاعات ارسال بررسی شود."
        if "tracking_code" in missing or "shipping_method" in missing:
            return "ضمن تشکر، لطفاً نحوه ارسال و کد رهگیری مرسوله را ارسال فرمایید."
        return "اطلاعات ارسال دریافت شد و در دست بررسی قرار گرفت."

    if is_delivery_completed_seller_message(seller_text):
        if order_ids:
            return "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
        return "لطفاً شماره سفارش را ارسال کنید تا درخواست تحویل بررسی شود."

    if is_shipment_seller_message(seller_text):
        if not order_ids:
            return "لطفاً شماره سفارش را ارسال کنید تا اطلاعات ارسال بررسی شود."
        if not tracking_code:
            return "ضمن تشکر، لطفاً نحوه ارسال و کد رهگیری مرسوله را ارسال فرمایید."
        return "اطلاعات ارسال دریافت شد و در دست بررسی قرار گرفت."

    if is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    ):
        return build_sheba_issue_draft_response(
            seller_text,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )

    if scenario == _SCENARIO_PRODUCT_APPROVAL:
        if product_ids:
            return PRODUCT_REVIEW_ACK
        return PRODUCT_ID_REQUEST

    if should_request_photo_file(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    ):
        return DEFAULT_PHOTO_FILE_REQUEST

    if any(marker in seller_text for marker in ("برند", "brand")):
        if any(token in seller_text for token in ("پیدا نمی", "پیدا نمیکنم", "پیدا نمی‌کنم")):
            return BRAND_NAME_REQUEST
        return GENERIC_REVIEW_ACK

    policy_answer = _policy_answer_template(
        action=action,
        intent=intent,
        seller_text=seller_text,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )
    if policy_answer is not None:
        return policy_answer

    if is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    ):
        return "تسویه سفارش‌ها پس از نهایی شدن فرآیند سفارش انجام می‌شود."

    if action == "update_delivery_status" or "delivery" in intent:
        if order_ids:
            return (
                f"شماره سفارش {order_ids[0]} دریافت شد؛ "
                "برای ثبت تحویل، وضعیت ارسال در سامانه بررسی می‌شود."
            )
        return "لطفاً شماره سفارش را ارسال کنید تا ثبت تحویل انجام شود."

    if action in {"check_return_request"} or "return" in intent or "refund" in intent:
        return "درخواست شما دریافت شد و توسط تیم مربوطه بررسی خواهد شد."

    if action in {"escalate", "human_followup"} or "complaint" in intent:
        return (
            "با توجه به توضیحات شما، موضوع شکایت برای بررسی و بستن پرونده در اولویت قرار گرفته است."
        )

    if action == "check_order_status" or "order_status" in intent:
        if order_ids:
            return (
                f"وضعیت سفارش {order_ids[0]} در سامانه بررسی می‌شود "
                "و نتیجه از همین مسیر اطلاع‌رسانی می‌شود."
            )
        return "لطفاً شماره سفارش را ارسال کنید تا وضعیت سفارش بررسی شود."

    if action == "answer_policy_question" or "policy" in intent or "prohibited" in intent:
        policy_answer = _policy_answer_template(
            action=action,
            intent=intent,
            seller_text=seller_text,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
        return policy_answer or (
            "پاسخ شما بر اساس قوانین و راهنمای مرتبط با درخواست‌تان ارائه می‌شود."
        )

    if product_ids and not order_ids:
        return "شناسه محصول دریافت شد؛ درخواست شما برای بررسی ثبت شده است."

    return "درخواست شما دریافت شد و مطابق اقدام پیشنهادی بررسی می‌شود."


def generate_mock_operational_draft(
    inputs: MockOperationalDraftInput,
    *,
    max_chars: int = MOCK_OPERATIONAL_DRAFT_MAX_CHARS,
) -> str:
    """Build a concise deterministic Persian draft (mock/offline only)."""
    validation = _actionability_validation(inputs)
    scenario = detect_operational_scenario(
        seller_text=inputs.seller_text,
        detected_intent=inputs.detected_intent,
        suggested_action=inputs.suggested_action,
        conceptual_intent_fa=inputs.conceptual_intent_fa,
    )
    sheba_kwargs = {
        "extracted_iban": inputs.extracted_iban,
        "has_incomplete_iban_entity": inputs.has_incomplete_iban_entity,
        "entity_warnings_summary": inputs.entity_warnings_summary,
    }
    if scenario in {_SCENARIO_CANCELLATION, _SCENARIO_DELIVERY_COMPLETED, _SCENARIO_SHIPMENT}:
        draft = _template_for_operational_case(
            suggested_action=inputs.suggested_action or "",
            detected_intent=inputs.detected_intent or "",
            seller_text=inputs.seller_text,
            order_ids=inputs.order_ids,
            product_ids=inputs.product_ids,
            tracking_code=inputs.tracking_code,
            **sheba_kwargs,
        )
    elif validation.should_request_identifier:
        draft = build_missing_identifier_request(
            validation.missing_required_entities,
            requested_action=validation.requested_action,
            seller_text=inputs.seller_text,
        )
    else:
        draft = _template_for_operational_case(
            suggested_action=inputs.suggested_action or "",
            detected_intent=inputs.detected_intent or "",
            seller_text=inputs.seller_text,
            order_ids=inputs.order_ids,
            product_ids=inputs.product_ids,
            tracking_code=inputs.tracking_code,
            **sheba_kwargs,
        )

    draft = _truncate_mock_draft(draft, max_chars=max_chars)
    assert_draft_reply_safe(draft, max_chars=max_chars)
    if "خروجی آزمایشی" in draft:
        raise ValueError("mock operational draft must not contain mock LLM placeholder text")
    return draft
