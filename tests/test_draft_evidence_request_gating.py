"""Regression tests for opt-in photo/file evidence request gating."""

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
from app.evals.draft_evidence_wording_calibration import (
    BRAND_NAME_REQUEST,
    PRODUCT_ID_REQUEST,
    PRODUCT_REVIEW_ACK,
    apply_photo_evidence_wording_calibration,
    build_photo_evidence_wording_instruction,
    calibrate_photo_evidence_wording,
    draft_requests_photo_evidence,
    should_request_photo_file,
)
from app.evals.draft_style import DRAFT_STYLE_OPERATIONAL_SHORT
from app.knowledge.policy_fact_extraction import (
    SHEBA_NUMBER_REQUEST,
    build_sheba_issue_draft_response,
)
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_PHOTO_FORBIDDEN = (
    "عکس",
    "تصویر",
    "فایل عکس",
    "اسکرین",
    "screenshot",
)

_SHEBA_WITH_IBAN = "سلام هر کار میکنم شماره شبام ثبت نمیشه شماره شبا IR120170000000123456789001"
_SHEBA_WITHOUT_IBAN = "سلام شماره شبام ثبت نمیشه"
_PRODUCT_NO_ID = "کالای من تایید نشده"
_PRODUCT_WITH_ID = "کالای 12345678 تایید نشده"
_BRAND_NOT_FOUND = "برند مورد نظر را در صفحه پیدا نمی‌کنم"
_EXPLICIT_PHOTO = "چطور عکس کالا را تغییر بدهم؟"


def _assert_no_photo_request(text: str) -> None:
    lowered = text.lower()
    for marker in _PHOTO_FORBIDDEN:
        assert marker not in text and marker not in lowered


def test_sheba_issue_with_iban_no_photo_request() -> None:
    assert should_request_photo_file(_SHEBA_WITH_IBAN) is False
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_WITH_IBAN,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
        ),
    )
    _assert_no_photo_request(draft)
    assert "شبا" in draft or "بررسی" in draft


def test_sheba_issue_without_iban_asks_sheba_not_photo() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_WITHOUT_IBAN,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
        ),
    )
    _assert_no_photo_request(draft)
    result = apply_photo_evidence_wording_calibration(
        "لطفاً فایل عکس از شماره شبای خود را ارسال کنید.",
        seller_text=_SHEBA_WITHOUT_IBAN,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="billing_review",
    )
    assert result.unnecessary_photo_request_detected is True
    assert result.draft_reply == SHEBA_NUMBER_REQUEST


def test_product_issue_without_product_id_asks_id_not_photo() -> None:
    assert should_request_photo_file(_PRODUCT_NO_ID) is False
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_PRODUCT_NO_ID,
            detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
            suggested_action="check_product_approval",
        ),
    )
    assert "شناسه کالا" in draft
    _assert_no_photo_request(draft)


def test_product_issue_with_product_id_acknowledges_not_photo() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_PRODUCT_WITH_ID,
            detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
            suggested_action="check_product_approval",
            product_ids=("12345678",),
        ),
    )
    assert draft == PRODUCT_REVIEW_ACK
    _assert_no_photo_request(draft)


def test_brand_not_found_asks_brand_name_not_screenshot() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_BRAND_NOT_FOUND,
            detected_intent=VendorTicketIntent.SELLER_OPERATIONAL_REQUEST.value,
            suggested_action="human_followup",
        ),
    )
    assert draft == BRAND_NAME_REQUEST
    _assert_no_photo_request(draft)

    bad = "لطفاً تصویر صفحه‌ای که در آن برند مورد نظر را نمی‌توانید پیدا کنید ارسال کنید."
    result = apply_photo_evidence_wording_calibration(
        bad,
        seller_text=_BRAND_NOT_FOUND,
        suggested_action="human_followup",
    )
    assert result.unnecessary_photo_request_detected is True
    assert draft_requests_photo_evidence(result.draft_reply) is False
    assert "برند" in result.draft_reply


def test_explicit_photo_context_allows_photo_wording() -> None:
    assert should_request_photo_file(_EXPLICIT_PHOTO) is True
    instruction = build_photo_evidence_wording_instruction(seller_text=_EXPLICIT_PHOTO)
    assert "فایل عکس" in instruction
    calibrated, changed, unnecessary = calibrate_photo_evidence_wording(
        "لطفاً شناسه عکس را وارد کنید.",
        seller_text=_EXPLICIT_PHOTO,
        detected_intent=VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value,
        suggested_action="answer_policy_question",
    )
    assert changed is True
    assert unnecessary is False
    assert "شناسه عکس" not in calibrated
    assert "فایل عکس" in calibrated or "تصویر کالا" in calibrated


def test_photo_id_replaced_with_file_wording_when_photo_context_explicit() -> None:
    calibrated, changed, unnecessary = calibrate_photo_evidence_wording(
        "لطفاً شناسه عکس را وارد کنید.",
        seller_text="لطفاً عکس کالا را بررسی کنید",
    )
    assert changed is True
    assert unnecessary is False
    assert "شناسه عکس" not in calibrated


def test_photo_request_without_context_is_stripped_or_replaced() -> None:
    bad = "لطفاً فایل عکس از کالای بارگذاری‌شده را ارسال کنید."
    result = apply_photo_evidence_wording_calibration(
        bad,
        seller_text=_PRODUCT_NO_ID,
        detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        suggested_action="check_product_approval",
        missing_entities=("product_id",),
    )
    assert result.unnecessary_photo_request_detected is True
    _assert_no_photo_request(result.draft_reply)
    assert result.draft_reply == PRODUCT_ID_REQUEST

    sheba_bad = "لطفاً فایل عکس از شماره شبای خود را ارسال کنید."
    sheba_result = apply_photo_evidence_wording_calibration(
        sheba_bad,
        seller_text=_SHEBA_WITH_IBAN,
        suggested_action="billing_review",
    )
    assert sheba_result.unnecessary_photo_request_detected is True
    _assert_no_photo_request(sheba_result.draft_reply)
    assert sheba_result.draft_reply == build_sheba_issue_draft_response(
        _SHEBA_WITH_IBAN,
        extracted_iban="120170000000123456789001",
    )


def test_openai_prompt_includes_negative_photo_guardrails() -> None:
    context = OpenAIDraftPromptContext(
        room_id="ROOM-PHOTO",
        seller_text=_PRODUCT_NO_ID,
        detected_intent=VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        conceptual_intent_fa="تأیید کالا",
        suggested_action="check_product_approval",
        suggested_action_reason="test",
        ticket_label="product",
        route_label="product_review",
        order_ids=(),
        product_ids=(),
        tracking_code=None,
        knowledge_hint_document_types=(),
        actionability=ActionabilityValidationResult(
            actionable=False,
            missing_required_entities=("product_id",),
            requested_action="check_product_approval",
            validation_reason="test",
            should_request_identifier=True,
        ),
        target_max_chars=300,
        hard_max_chars=300,
        draft_style=DRAFT_STYLE_OPERATIONAL_SHORT,
        max_sentences=2,
    )
    combined = "\n".join(message.content for message in build_openai_draft_prompt(context))
    assert "درخواست عکس، تصویر یا اسکرین‌شات نکن" in combined
    assert "شناسه کالا را بخواه نه عکس کالا" in combined
    assert "عکس شبا نخواه" in combined
