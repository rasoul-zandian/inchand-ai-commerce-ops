"""Tests for Sheba/IBAN draft responses based on entity extraction."""

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
from app.evals.draft_style import DRAFT_STYLE_OPERATIONAL_SHORT
from app.knowledge.policy_fact_extraction import (
    SHEBA_INCOMPLETE_REQUEST,
    SHEBA_NUMBER_REQUEST,
    SHEBA_RECEIVED_ACK,
    build_sheba_issue_draft_response,
    calibrate_sheba_issue_draft,
)
from app.workflows.operational_entity_extraction import extract_operational_entities
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_SHEBA_WITH_IBAN = "سلام هر کار میکنم شماره شبام ثبت نمیشه شماره شبا IR120170000000123456789001"
_SHEBA_WITHOUT_IBAN = "سلام شماره شبام ثبت نمیشه"
_ACCOUNT_WITH_IBAN = (
    "جهت ثبت اطلاعات تسویه حساب پنل و شماره شبا IR120170000000123456789001 ثبت گردد"
)
_PHOTO_FORBIDDEN = ("عکس", "تصویر", "فایل عکس", "اسکرین", "screenshot")


def _assert_no_photo_request(text: str) -> None:
    lowered = text.lower()
    for marker in _PHOTO_FORBIDDEN:
        assert marker not in text and marker not in lowered


def test_sheba_with_valid_iban_extracted_acknowledges_no_reask() -> None:
    extracted = extract_operational_entities(_SHEBA_WITH_IBAN)
    assert extracted.primary_iban is not None

    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_WITH_IBAN,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
            extracted_iban=extracted.primary_iban,
        ),
    )
    assert SHEBA_RECEIVED_ACK in draft or "شماره شبا دریافت شد" in draft
    assert SHEBA_NUMBER_REQUEST not in draft
    _assert_no_photo_request(draft)

    calibrated, changed = calibrate_sheba_issue_draft(
        SHEBA_NUMBER_REQUEST,
        seller_text=_SHEBA_WITH_IBAN,
        extracted_iban=extracted.primary_iban,
    )
    assert changed is True
    assert calibrated == SHEBA_RECEIVED_ACK


def test_sheba_without_iban_asks_correct_number() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_WITHOUT_IBAN,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
        ),
    )
    assert draft == SHEBA_NUMBER_REQUEST
    _assert_no_photo_request(draft)


def test_incomplete_iban_candidate_asks_corrected_sheba() -> None:
    result = extract_operational_entities("شماره شبا 12345678901234567890123")
    assert result.has_incomplete_iban_candidate is True
    assert result.primary_iban is None

    draft = build_sheba_issue_draft_response(
        "شماره شبا 12345678901234567890123",
        has_incomplete_iban_entity=True,
    )
    assert draft == SHEBA_INCOMPLETE_REQUEST

    mock_draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text="شماره شبا 12345678901234567890123",
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
            has_incomplete_iban_entity=True,
        ),
    )
    assert mock_draft == SHEBA_INCOMPLETE_REQUEST


def test_account_registration_with_valid_iban_acknowledges() -> None:
    extracted = extract_operational_entities(_ACCOUNT_WITH_IBAN)
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_ACCOUNT_WITH_IBAN,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
            extracted_iban=extracted.primary_iban,
        ),
    )
    assert "شماره شبا" in draft
    assert SHEBA_NUMBER_REQUEST not in draft
    _assert_no_photo_request(draft)


def test_sheba_cases_never_request_photo() -> None:
    for seller in (_SHEBA_WITH_IBAN, _SHEBA_WITHOUT_IBAN, _ACCOUNT_WITH_IBAN):
        draft = generate_mock_operational_draft(
            MockOperationalDraftInput(
                seller_text=seller,
                detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
                suggested_action="check_settlement_status",
            ),
        )
        _assert_no_photo_request(draft)


def test_openai_prompt_includes_extraction_dependent_sheba_rule() -> None:
    context = OpenAIDraftPromptContext(
        room_id="ROOM-SHEBA",
        seller_text=_SHEBA_WITH_IBAN,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        conceptual_intent_fa="ثبت شبا",
        suggested_action="check_settlement_status",
        suggested_action_reason="test",
        ticket_label="fund",
        route_label="billing_review",
        order_ids=(),
        product_ids=(),
        tracking_code=None,
        knowledge_hint_document_types=(),
        actionability=ActionabilityValidationResult(
            actionable=True,
            missing_required_entities=(),
            requested_action="check_settlement_status",
            validation_reason="test",
            should_request_identifier=False,
        ),
        target_max_chars=300,
        hard_max_chars=300,
        draft_style=DRAFT_STYLE_OPERATIONAL_SHORT,
        max_sentences=2,
        extracted_iban="120170000000123456789001",
        has_incomplete_iban_entity=False,
    )
    combined = "\n".join(message.content for message in build_openai_draft_prompt(context))
    assert "شماره شبا از پیام فروشنده استخراج شده است" in combined
    assert "دوباره شماره شبا نخواه" in combined
