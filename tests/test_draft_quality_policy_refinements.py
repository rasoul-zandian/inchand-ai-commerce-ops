"""Tests for Step 216 draft quality policy refinements."""

from __future__ import annotations

from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.evals.draft_completion_calibration import (
    apply_draft_completion_calibration,
    strip_trailing_contact_closing_filler,
)
from app.evals.draft_evidence_wording_calibration import calibrate_photo_evidence_wording
from app.evals.draft_style import (
    DRAFT_STYLE_POLICY_EXPLANATION,
    apply_draft_style_checks,
    resolve_effective_draft_style,
    validate_policy_explanation_draft,
)
from app.knowledge.policy_fact_extraction import SETTLEMENT_CANONICAL_DRAFT_ANSWER
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_SETTLEMENT_QUESTION = "بعد از خرید کالا توسط مشتری، چند روز دیگه میتونم تسویه کنم؟"
_CONTACT_FILLER = "در صورت نیاز به اطلاعات بیشتر، لطفاً با ما تماس بگیرید."


def test_delivery_acknowledgement_strips_contact_filler() -> None:
    seller = "سفارش 8057168 تحویل گیرنده شده"
    draft = f"درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت. {_CONTACT_FILLER}"
    result = apply_draft_completion_calibration(
        draft,
        seller_text=seller,
        suggested_action="update_delivery_status",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
    )
    assert result.contact_closing_filler_removed is True
    assert _CONTACT_FILLER not in result.draft_reply
    assert "درخواست تحویل سفارش" in result.draft_reply


def test_cancellation_acknowledgement_strips_contact_filler() -> None:
    seller = "سفارش 7439040 لغو شود"
    draft = f"درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت. {_CONTACT_FILLER}"
    cleaned, removed = strip_trailing_contact_closing_filler(draft, seller_text=seller)
    assert removed is True
    assert _CONTACT_FILLER not in cleaned


def test_policy_answer_strips_contact_filler() -> None:
    draft = f"{SETTLEMENT_CANONICAL_DRAFT_ANSWER} {_CONTACT_FILLER}"
    result = apply_draft_completion_calibration(
        draft,
        seller_text=_SETTLEMENT_QUESTION,
        suggested_action="check_settlement_status",
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
    )
    assert result.contact_closing_filler_removed is True
    assert _CONTACT_FILLER not in result.draft_reply


def test_photo_request_uses_file_wording_not_photo_id() -> None:
    bad = "لطفاً شناسه عکس را وارد کنید."
    calibrated, changed, _unnecessary = calibrate_photo_evidence_wording(
        bad,
        seller_text="لطفاً عکس کالا را بررسی کنید",
    )
    assert changed is True
    assert "شناسه عکس" not in calibrated
    assert "فایل عکس" in calibrated or "تصویر کالا" in calibrated


def test_settlement_policy_question_uses_policy_explanation_style() -> None:
    assert (
        resolve_effective_draft_style(
            seller_text=_SETTLEMENT_QUESTION,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
        )
        == DRAFT_STYLE_POLICY_EXPLANATION
    )
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SETTLEMENT_QUESTION,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
        ),
        max_chars=700,
    )
    assert "کیف پول" in draft
    assert "۳ روز" in draft
    assert "راهنما" not in draft
    validation = validate_policy_explanation_draft(draft)
    assert validation.draft_style_ok is True
    assert validation.draft_char_count >= len(SETTLEMENT_CANONICAL_DRAFT_ANSWER) - 5


def test_operational_acknowledgement_remains_short_style() -> None:
    seller = "سفارش 8057168 تحویل گیرنده شده"
    style = resolve_effective_draft_style(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    )
    assert style != DRAFT_STYLE_POLICY_EXPLANATION
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=("8057168",),
        ),
    )
    from app.config import AppSettings

    validation = apply_draft_style_checks(
        draft,
        AppSettings(),
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    )
    assert validation.draft_style == "operational_short"
    assert validation.draft_style_ok is True
