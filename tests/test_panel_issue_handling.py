"""Regression tests for seller panel/shop access issue draft handling."""

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
from app.workflows.operational_information_sufficiency import (
    PANEL_ISSUE_NAZER_REVIEW_RESPONSE,
    apply_panel_issue_draft_calibration,
    build_panel_issue_response,
    detect_operational_scenario,
    is_seller_panel_issue,
    refine_suggested_action_for_panel_issue,
)
from app.workflows.suggested_action_taxonomy import map_intent_to_suggested_action
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent


def _actionability(**kwargs: object) -> ActionabilityValidationResult:
    base = {
        "actionable": True,
        "missing_required_entities": (),
        "requested_action": "human_followup",
        "validation_reason": "test",
        "should_request_identifier": False,
    }
    base.update(kwargs)
    return ActionabilityValidationResult(**base)  # type: ignore[arg-type]


def test_panel_issue_unresolved_with_shop_id_returns_nazer_review() -> None:
    seller = "سلام مشکل پنل من حل نشد؟"
    assert is_seller_panel_issue(seller)
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=seller,
            detected_intent=VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value,
            suggested_action="request_missing_info",
            shop_id="4136",
        ),
    )
    assert PANEL_ISSUE_NAZER_REVIEW_RESPONSE in draft or build_panel_issue_response() in draft
    assert "شناسه پنل" not in draft
    assert "شناسه فروشگاه" not in draft


def test_panel_closed_requests_nazer_review() -> None:
    seller = "پنلم بسته شده لطفا پیگیری کنید"
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=seller,
            suggested_action="human_followup",
        ),
    )
    assert "ناظر" in draft
    assert "شناسه پنل" not in draft


def test_products_not_visible_in_panel_is_panel_issue() -> None:
    seller = "محصولاتم در پنل نمایش داده نمی‌شود"
    assert is_seller_panel_issue(seller)
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent="general_inquiry",
            suggested_action="human_followup",
        )
        == "panel_issue"
    )


def test_sheba_in_panel_wins_over_panel_issue() -> None:
    seller = "شماره شبام در پنل ثبت نمیشه IR120170000000100000000001"
    assert not is_seller_panel_issue(seller)
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=seller,
            suggested_action="check_settlement_status",
        ),
    )
    assert "شناسه پنل" not in draft
    assert "شبا" in draft or "شماره" in draft


def test_delivery_request_wins_over_panel_issue() -> None:
    seller = "لطفا سفارش INC-1234567 را تحویل شده بزنید"
    assert not is_seller_panel_issue(seller)
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        != "panel_issue"
    )


def test_openai_prompt_includes_panel_no_id_rule() -> None:
    messages = build_openai_draft_prompt(
        OpenAIDraftPromptContext(
            room_id="ROOM-1",
            seller_text="پنلم بسته شده",
            detected_intent=VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value,
            conceptual_intent_fa="مشکل پنل تسویه",
            suggested_action="human_followup",
            suggested_action_reason="panel review",
            ticket_label="support",
            route_label="general_vendor_support",
            order_ids=(),
            product_ids=(),
            tracking_code=None,
            knowledge_hint_document_types=(),
            actionability=_actionability(),
            target_max_chars=300,
            hard_max_chars=700,
            shop_id_available=True,
            panel_issue_detected=True,
        ),
    )
    combined = "\n".join(message.content for message in messages)
    assert "panel_issue_detected" in combined or "مشکل دسترسی" in combined
    assert "shop_id" in combined.lower() or "shop_id_available" in combined
    assert "شناسه پنل" in combined or "panel/shop" in combined


def test_post_processing_replaces_panel_id_request() -> None:
    bad = "لطفاً شناسه پنل را ارسال کنید تا بررسی انجام شود."
    calibrated, metrics = apply_panel_issue_draft_calibration(
        bad,
        seller_text="مشکل پنل من حل نشد",
        shop_id="99",
    )
    assert metrics["panel_id_request_suppressed"] is True
    assert calibrated == build_panel_issue_response()
    assert "شناسه پنل" not in calibrated


def test_request_missing_info_refined_to_human_followup_for_panel() -> None:
    action, reason = refine_suggested_action_for_panel_issue(
        "request_missing_info",
        "پنلم بسته شده",
        shop_id="4136",
    )
    assert action == "human_followup"
    assert reason is not None
    assert "shop_id" in reason

    class _WarnEntities:
        entity_warnings_summary = "incomplete extraction"

    mapping = map_intent_to_suggested_action(
        VendorTicketIntent.UNKNOWN,
        normalized_text="پنلم بسته شده",
        entities=_WarnEntities(),
    )
    assert mapping.action.value == "human_followup"
