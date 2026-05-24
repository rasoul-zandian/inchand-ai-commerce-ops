"""Operational actionability validation — missing identifiers must be requested, not faked."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
)
from app.workflows.suggested_action_taxonomy import (
    _DELIVERY_CONCEPTUAL_MARKERS,
    _ORDER_STATUS_CONCEPTUAL_MARKERS,
    _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS,
    _PRODUCT_EDIT_MARKERS,
    _RETURN_REFUND_MARKERS,
    _has_any,
)
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_ENTITY_ORDER_ID = "order_id"
_ENTITY_PRODUCT_ID = "product_id"
_ENTITY_TRACKING_CODE = "tracking_code"

_ACTION_REQUIRED_ENTITIES: dict[str, tuple[str, ...]] = {
    "update_delivery_status": (_ENTITY_ORDER_ID,),
    "check_order_status": (_ENTITY_ORDER_ID,),
    "check_return_request": (_ENTITY_ORDER_ID,),
    "check_product_approval": (_ENTITY_PRODUCT_ID,),
    "review_product_edit": (_ENTITY_PRODUCT_ID,),
    "record_update": (),  # satisfied by tracking OR order_id
    "check_settlement_status": (),
    "answer_policy_question": (),
    "billing_review": (),
    "monitor": (),
    "escalate": (),
    "human_followup": (),
    "request_missing_info": (),
    "duplicate_check": (),
    "route_review": (),
}

_FAKE_OPERATIONAL_CLAIM_MARKERS = (
    "درخواست شما ثبت شد",
    "درخواست شما با موفقیت ثبت شد",
    "ثبت شد",
    "ارجاع شد",
    "به تیم مربوطه ارجاع",
    "برای بررسی به تیم",
    "در حال بررسی",
    "مورد در حال بررسی",
    "بررسی لازم انجام شد",
    "پیگیری خواهد شد",
    "پیگیری می‌شود",
    "پیگیری میشود",
    "انجام شد",
    "انجام می‌شود",
    "شروع شد",
    "شروع می‌شود",
    "در صف بررسی",
    "در صف پیگیری",
)

_IDENTIFIER_REQUEST_TEMPLATES: dict[str, str] = {
    _ENTITY_ORDER_ID: (
        "لطفاً شماره سفارش را ارسال کنید تا امکان بررسی و پیگیری درخواست شما وجود داشته باشد."
    ),
    _ENTITY_PRODUCT_ID: ("لطفاً شناسه کالا را ارسال کنید تا بررسی و تایید انجام شود."),
    _ENTITY_TRACKING_CODE: (
        "لطفاً کد رهگیری یا شماره سفارش مرتبط را ارسال کنید تا ثبت و پیگیری انجام شود."
    ),
}

_ACTION_SPECIFIC_ORDER_TEMPLATES: dict[str, str] = {
    "update_delivery_status": (
        "لطفاً شماره سفارش را ارسال کنید تا امکان بررسی و ثبت تحویل وجود داشته باشد."
    ),
    "check_product_approval": ("لطفاً شناسه کالا را ارسال کنید تا بررسی و تایید انجام شود."),
    "check_return_request": ("لطفاً شماره سفارش را ارسال کنید تا درخواست مرجوعی بررسی شود."),
    "check_order_status": ("لطفاً شماره سفارش را ارسال کنید تا وضعیت سفارش قابل بررسی باشد."),
    "review_product_edit": ("لطفاً شناسه کالا را ارسال کنید تا درخواست ویرایش کالا بررسی شود."),
    "record_update": (
        "لطفاً کد رهگیری یا شماره سفارش را ارسال کنید تا ثبت اطلاعات ارسال انجام شود."
    ),
}


@dataclass(frozen=True)
class ActionabilityValidationResult:
    """Whether an operational suggested action can proceed with extracted identifiers."""

    actionable: bool
    missing_required_entities: tuple[str, ...]
    requested_action: str
    validation_reason: str
    should_request_identifier: bool

    @property
    def requires_identifier_request(self) -> bool:
        return self.should_request_identifier


def _normalize_action(action: str) -> str:
    return (action or "").strip().lower()


def _has_order_ids(order_ids: Sequence[str]) -> bool:
    return any(str(value).strip() for value in order_ids)


def _has_product_ids(product_ids: Sequence[str]) -> bool:
    return any(str(value).strip() for value in product_ids)


def _has_tracking(tracking_code: str | None) -> bool:
    return bool(tracking_code and str(tracking_code).strip())


def _human_followup_required_entities(
    seller_text: str,
    *,
    detected_intent: str | None,
) -> tuple[str, ...]:
    blob = seller_text.strip()
    if not blob:
        intent = (detected_intent or "").strip().lower()
        if intent == VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value:
            return (_ENTITY_ORDER_ID,)
        if intent == VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value:
            return (_ENTITY_PRODUCT_ID,)
        if intent == VendorTicketIntent.ORDER_STATUS_REVIEW.value:
            return (_ENTITY_ORDER_ID,)
        return ()

    required: list[str] = []
    if _has_any(blob, _DELIVERY_CONCEPTUAL_MARKERS):
        required.append(_ENTITY_ORDER_ID)
    if _has_any(blob, _ORDER_STATUS_CONCEPTUAL_MARKERS):
        if _ENTITY_ORDER_ID not in required:
            required.append(_ENTITY_ORDER_ID)
    if _has_any(blob, _PRODUCT_APPROVAL_CONCEPTUAL_MARKERS):
        required.append(_ENTITY_PRODUCT_ID)
    if _has_any(blob, _PRODUCT_EDIT_MARKERS):
        required.append(_ENTITY_PRODUCT_ID)
    if _has_any(blob, _RETURN_REFUND_MARKERS):
        if _ENTITY_ORDER_ID not in required:
            required.append(_ENTITY_ORDER_ID)
    return tuple(required)


def required_entities_for_action(
    action: str,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
) -> tuple[str, ...]:
    """Return entity keys required before claiming operational progress."""
    normalized = _normalize_action(action)
    if normalized == "human_followup":
        return _human_followup_required_entities(
            seller_text,
            detected_intent=detected_intent,
        )
    return _ACTION_REQUIRED_ENTITIES.get(normalized, ())


def _missing_entities(
    required: Sequence[str],
    *,
    order_ids: Sequence[str],
    product_ids: Sequence[str],
    tracking_code: str | None,
    action: str,
) -> tuple[str, ...]:
    missing: list[str] = []
    normalized = _normalize_action(action)

    if normalized == "record_update":
        if not _has_tracking(tracking_code) and not _has_order_ids(order_ids):
            return (_ENTITY_TRACKING_CODE, _ENTITY_ORDER_ID)
        return ()

    for entity in required:
        if entity == _ENTITY_ORDER_ID and not _has_order_ids(order_ids):
            missing.append(_ENTITY_ORDER_ID)
        elif entity == _ENTITY_PRODUCT_ID and not _has_product_ids(product_ids):
            missing.append(_ENTITY_PRODUCT_ID)
        elif entity == _ENTITY_TRACKING_CODE and not _has_tracking(tracking_code):
            missing.append(_ENTITY_TRACKING_CODE)
    return tuple(missing)


def validate_actionability(
    *,
    suggested_action: str,
    order_ids: Sequence[str] | None = None,
    product_ids: Sequence[str] | None = None,
    tracking_code: str | None = None,
    seller_text: str = "",
    detected_intent: str | None = None,
    entities: OperationalEntityExtractionResult | Any | None = None,
) -> ActionabilityValidationResult:
    """Validate whether required identifiers are present for the suggested action."""
    action = _normalize_action(suggested_action)
    orders = list(order_ids or [])
    products = list(product_ids or [])
    tracking = tracking_code

    if entities is not None:
        if not orders:
            orders = list(
                getattr(entities, "extracted_order_ids", None)
                or getattr(entities, "order_ids", ())
                or [],
            )
        if not products:
            products = list(
                getattr(entities, "extracted_product_ids", None)
                or getattr(entities, "product_ids", ())
                or [],
            )
        if tracking is None:
            tracking = getattr(entities, "extracted_tracking_code", None) or getattr(
                entities,
                "primary_tracking_code",
                None,
            )

    required = required_entities_for_action(
        action,
        seller_text=seller_text,
        detected_intent=detected_intent,
    )
    missing = _missing_entities(
        required,
        order_ids=orders,
        product_ids=products,
        tracking_code=tracking,
        action=action,
    )

    if missing:
        reason = f"missing_{'_'.join(missing)}_for_{action or 'unknown'}"
        return ActionabilityValidationResult(
            actionable=False,
            missing_required_entities=missing,
            requested_action=action,
            validation_reason=reason,
            should_request_identifier=True,
        )

    if action == "request_missing_info":
        return ActionabilityValidationResult(
            actionable=False,
            missing_required_entities=(_ENTITY_ORDER_ID,),
            requested_action=action,
            validation_reason="entity_warnings_or_incomplete_extraction",
            should_request_identifier=True,
        )

    return ActionabilityValidationResult(
        actionable=True,
        missing_required_entities=(),
        requested_action=action,
        validation_reason="required_entities_present",
        should_request_identifier=False,
    )


def validate_actionability_from_text(
    seller_text: str,
    *,
    suggested_action: str,
    detected_intent: str | None = None,
) -> ActionabilityValidationResult:
    """Validate using freshly extracted entities from seller text."""
    entities = extract_operational_entities(seller_text)
    return validate_actionability(
        suggested_action=suggested_action,
        order_ids=entities.order_ids,
        product_ids=entities.product_ids,
        tracking_code=entities.primary_tracking_code,
        seller_text=seller_text,
        detected_intent=detected_intent,
        entities=entities,
    )


def build_missing_identifier_request(
    missing_entities: Sequence[str],
    *,
    requested_action: str = "",
    seller_text: str = "",
) -> str:
    """Deterministic Persian reply asking only for missing identifiers."""
    action = _normalize_action(requested_action)
    if action in _ACTION_SPECIFIC_ORDER_TEMPLATES and len(missing_entities) == 1:
        entity = missing_entities[0]
        if entity == _ENTITY_ORDER_ID or entity == _ENTITY_PRODUCT_ID:
            return _ACTION_SPECIFIC_ORDER_TEMPLATES[action]
        if entity == _ENTITY_TRACKING_CODE:
            return _ACTION_SPECIFIC_ORDER_TEMPLATES["record_update"]

    if len(missing_entities) == 1:
        template = _IDENTIFIER_REQUEST_TEMPLATES.get(missing_entities[0])
        if template:
            return template

    parts: list[str] = []
    if _ENTITY_ORDER_ID in missing_entities:
        parts.append("شماره سفارش")
    if _ENTITY_PRODUCT_ID in missing_entities:
        parts.append("شناسه کالا")
    if _ENTITY_TRACKING_CODE in missing_entities:
        parts.append("کد رهگیری یا شماره سفارش")
    joined = " و ".join(parts) if parts else "شناسه مرتبط"
    _ = seller_text
    return f"لطفاً {joined} را ارسال کنید تا درخواست شما قابل بررسی باشد."


def draft_claims_fake_operational_execution(draft: str) -> bool:
    """True when draft implies forwarding/review started without identifier request."""
    text = draft.strip()
    if not text:
        return False
    return any(marker in text for marker in _FAKE_OPERATIONAL_CLAIM_MARKERS)


def apply_actionability_to_draft(
    draft: str,
    validation: ActionabilityValidationResult,
    *,
    seller_text: str = "",
) -> tuple[str, ActionabilityValidationResult]:
    """Replace drafts that falsely claim operational execution when IDs are missing."""
    if not validation.should_request_identifier:
        return draft.strip(), validation

    cleaned = draft.strip()
    if draft_claims_fake_operational_execution(cleaned):
        replacement = build_missing_identifier_request(
            validation.missing_required_entities,
            requested_action=validation.requested_action,
            seller_text=seller_text,
        )
        return replacement, ActionabilityValidationResult(
            actionable=False,
            missing_required_entities=validation.missing_required_entities,
            requested_action=validation.requested_action,
            validation_reason=f"{validation.validation_reason}; replaced_fake_operational_claim",
            should_request_identifier=True,
        )
    return cleaned, validation


def build_actionability_prompt_instruction(
    validation: ActionabilityValidationResult,
) -> str:
    """Persian prompt fragment injected before draft generation."""
    if not validation.should_request_identifier:
        return (
            "- شناسه‌های لازم برای اقدام پیشنهادی در پیام اول موجود است؛ "
            "می‌توانی پاسخ عملیاتی کوتاه بدهی.\n"
        )
    missing_labels = ", ".join(validation.missing_required_entities) or "شناسه"
    return (
        "- اعتبارسنجی اقدام: شناسه لازم برای اقدام پیشنهادی در پیام اول موجود نیست.\n"
        f"- شناسه‌های مفقود: {missing_labels}\n"
        "- اگر شناسه لازم برای انجام درخواست وجود ندارد، فقط شناسه لازم را درخواست کن.\n"
        "- ادعای «ثبت شد»، «ارجاع شد»، «در حال بررسی»، «پیگیری خواهد شد» "
        "یا شروع/انجام بررسی نکن.\n"
        "- پاسخ باید فقط درخواست ارسال شناسه باشد (مثلاً شماره سفارش یا شناسه کالا).\n"
    )


def actionability_metadata_row(
    validation: ActionabilityValidationResult,
) -> dict[str, Any]:
    """Serializable fields for JSONL / operator preview."""
    return {
        "actionability": validation.actionable,
        "actionability_actionable": validation.actionable,
        "missing_required_entities": list(validation.missing_required_entities),
        "actionability_missing_entities": ",".join(validation.missing_required_entities) or None,
        "actionability_validation_reason": validation.validation_reason,
        "should_request_identifier": validation.should_request_identifier,
        "requires_identifier_request": validation.requires_identifier_request,
        "requested_action_validated": validation.requested_action,
    }
