"""Tests for operational actionability validation and draft safety replacement."""

from __future__ import annotations

from app.evals.actionability_validation import (
    apply_actionability_to_draft,
    build_missing_identifier_request,
    draft_claims_fake_operational_execution,
    required_entities_for_action,
    validate_actionability,
    validate_actionability_from_text,
)
from app.workflows.vendor_ticket_intent_detection import (
    VendorTicketIntent,
    detect_vendor_ticket_intent,
)


def test_delivery_request_without_order_id_not_actionable() -> None:
    seller = "چند سفارش هست تحویلش رو ثبت کنید"
    result = validate_actionability_from_text(
        seller,
        suggested_action="update_delivery_status",
    )
    assert result.actionable is False
    assert result.should_request_identifier is True
    assert "order_id" in result.missing_required_entities
    draft = build_missing_identifier_request(
        result.missing_required_entities,
        requested_action="update_delivery_status",
    )
    assert "شماره سفارش" in draft
    assert "ثبت تحویل" in draft


def test_product_approval_without_product_id() -> None:
    seller = "لطفا کالامو تایید کنید"
    result = validate_actionability_from_text(
        seller,
        suggested_action="check_product_approval",
    )
    assert result.actionable is False
    assert result.missing_required_entities == ("product_id",)
    draft = build_missing_identifier_request(
        result.missing_required_entities,
        requested_action="check_product_approval",
    )
    assert "شناسه کالا" in draft


def test_return_request_without_order_id() -> None:
    seller = "مرجوعی سفارش رو بررسی کنید"
    result = validate_actionability_from_text(
        seller,
        suggested_action="check_return_request",
    )
    assert result.actionable is False
    assert "order_id" in result.missing_required_entities
    draft = build_missing_identifier_request(
        result.missing_required_entities,
        requested_action="check_return_request",
    )
    assert "مرجوعی" in draft


def test_record_update_without_tracking_or_order() -> None:
    seller = "کد پستی رو ثبت کنید"
    result = validate_actionability_from_text(
        seller,
        suggested_action="record_update",
    )
    assert result.actionable is False
    assert set(result.missing_required_entities) == {"tracking_code", "order_id"}


def test_settlement_question_remains_actionable() -> None:
    seller = "تسویه من واریز نشده؟"
    result = validate_actionability_from_text(
        seller,
        suggested_action="check_settlement_status",
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
    )
    assert result.actionable is True
    assert not result.should_request_identifier


def test_deterministic_replacement_removes_fake_operational_claims() -> None:
    seller = "لطفا کالامو تایید کنید"
    validation = validate_actionability_from_text(
        seller,
        suggested_action="check_product_approval",
    )
    fake_draft = "درخواست شما ثبت شد و برای بررسی به تیم مربوطه ارجاع شد."
    assert draft_claims_fake_operational_execution(fake_draft)
    final, updated = apply_actionability_to_draft(
        fake_draft,
        validation,
        seller_text=seller,
    )
    assert "ارجاع" not in final
    assert "ثبت شد" not in final
    assert "شناسه کالا" in final
    assert "replaced_fake_operational_claim" in updated.validation_reason


def test_valid_operational_request_with_order_unchanged() -> None:
    seller = "سفارش 1234567 تحویل ثبت کنید"
    intent = detect_vendor_ticket_intent(seller)
    validation = validate_actionability(
        suggested_action="update_delivery_status",
        entities=intent,
        seller_text=seller,
        detected_intent=intent.detected_intent,
    )
    assert validation.actionable is True
    draft = "سفارش 1234567 در صف ثبت تحویل است."
    final, _ = apply_actionability_to_draft(draft, validation, seller_text=seller)
    assert final == draft


def test_required_entities_mapping() -> None:
    assert required_entities_for_action("check_order_status") == ("order_id",)
    assert required_entities_for_action("check_settlement_status") == ()
    assert required_entities_for_action(
        "human_followup",
        seller_text="ثبت تحویل سفارش",
    ) == ("order_id",)


def test_human_followup_delivery_without_order() -> None:
    seller = "ثبت تحویل سفارش"
    result = validate_actionability_from_text(
        seller,
        suggested_action="human_followup",
    )
    assert result.should_request_identifier is True
    assert "order_id" in result.missing_required_entities
