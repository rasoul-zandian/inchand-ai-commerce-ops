"""Tests for product/category wording normalization in support drafts."""

from __future__ import annotations

from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.agentic_sandbox.openai_draft_provider import (
    OpenAIDraftPromptContext,
    build_openai_draft_prompt,
)
from app.evals.actionability_validation import ActionabilityValidationResult
from app.evals.draft_product_wording_calibration import (
    apply_product_wording_calibration,
    build_product_wording_prompt_instruction,
    calibrate_product_reference_wording,
    detect_explicit_product_terms,
    is_product_support_context,
)
from app.evals.draft_style import DRAFT_STYLE_POLICY_EXPLANATION
from app.knowledge.policy_fact_extraction import SETTLEMENT_CANONICAL_DRAFT_ANSWER
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent


def _actionability(**kwargs: object) -> ActionabilityValidationResult:
    base = {
        "actionable": False,
        "missing_required_entities": ("product_id",),
        "requested_action": "check_product_approval",
        "validation_reason": "test",
        "should_request_identifier": True,
    }
    base.update(kwargs)
    return ActionabilityValidationResult(**base)  # type: ignore[arg-type]


def test_detect_explicit_product_terms_finds_bazi() -> None:
    seller = "چند تا بازی تعریف شده که نیاز به بررسی مجدد خورده"
    assert "بازی" in detect_explicit_product_terms(seller)


def test_calibrate_bazi_identifier_phrases() -> None:
    seller = "چند تا بازی تعریف شده که نیاز به بررسی مجدد خورده"
    bad = "برای بررسی علت نیاز به اصلاح بازی‌ها، لطفاً شناسه بازی‌ها را ارسال کنید."
    result = calibrate_product_reference_wording(
        bad,
        seller,
        context=None,
    )
    assert result.product_wording_normalized
    assert "بازی" not in result.calibrated_draft
    assert "شناسه کالاها" in result.calibrated_draft
    assert "اصلاح کالاها" in result.calibrated_draft


def test_adklan_request_uses_kala_identifier() -> None:
    seller = "ادکلن من تایید نشده"
    bad = "لطفاً شناسه ادکلن را ارسال کنید."
    calibrated, result = apply_product_wording_calibration(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        suggested_action="check_product_approval",
    )
    assert "شناسه کالا" in calibrated
    assert "شناسه ادکلن" not in calibrated
    assert result.product_wording_normalized


def test_ketab_plural_normalized_to_kalaha() -> None:
    seller = "کتاب‌ها رد شدند"
    bad = "برای بررسی کتاب‌ها لطفاً شناسه کتاب‌ها را ارسال کنید."
    calibrated, _ = apply_product_wording_calibration(
        bad,
        seller_text=seller,
        suggested_action="check_product_approval",
    )
    assert "کتاب" not in calibrated
    assert "کالاها" in calibrated


def test_order_cancellation_draft_unchanged() -> None:
    seller = "لطفاً سفارش 1234567 را لغو کنید"
    draft = "لطفاً شماره سفارش را ارسال کنید تا درخواست لغو بررسی شود."
    calibrated, result = apply_product_wording_calibration(
        draft,
        seller_text=seller,
        suggested_action="update_delivery_status",
    )
    assert calibrated == draft
    assert not result.product_wording_normalized


def test_policy_settlement_not_over_normalized() -> None:
    seller = "بعد از خرید چند روز تسویه می‌شود؟"
    draft = SETTLEMENT_CANONICAL_DRAFT_ANSWER
    calibrated, result = apply_product_wording_calibration(
        draft,
        seller_text=seller,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
    )
    assert calibrated == draft
    assert not result.product_wording_normalized


def test_openai_prompt_includes_product_wording_rule() -> None:
    instruction = build_product_wording_prompt_instruction(
        seller_text="چند تا بازی تعریف شده",
        detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        suggested_action="check_product_approval",
    )
    assert "کالا" in instruction
    assert "بازی" in instruction

    messages = build_openai_draft_prompt(
        OpenAIDraftPromptContext(
            room_id="R1",
            seller_text="چند تا بازی تعریف شده",
            detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
            conceptual_intent_fa="تایید کالا",
            suggested_action="check_product_approval",
            suggested_action_reason="product review",
            ticket_label="support",
            route_label="general_vendor_support",
            order_ids=(),
            product_ids=(),
            tracking_code=None,
            knowledge_hint_document_types=(),
            actionability=_actionability(),
            target_max_chars=300,
            hard_max_chars=700,
        ),
    )
    combined = "\n".join(m.content for m in messages)
    assert "کالا" in combined
    assert "بازی" in combined


def test_mock_draft_with_product_id_uses_kala_ack() -> None:
    seller = "وقت بخیر چند تا بازی تعریف شده که نیاز به بررسی مجدد خورده"
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=seller,
            detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
            suggested_action="check_product_approval",
            product_ids=("12345",),
            actionability={
                "actionability_actionable": True,
                "should_request_identifier": False,
            },
        ),
    )
    assert "بازی" not in draft
    assert "کالا" in draft


def test_is_product_support_context_for_game_review() -> None:
    seller = "چند تا بازی تعریف شده که نیاز به بررسی مجدد خورده"
    assert is_product_support_context(
        seller_text=seller,
        suggested_action="human_followup",
    )
