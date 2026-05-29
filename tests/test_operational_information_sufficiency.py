"""Tests for operational information sufficiency policies (Step 215)."""

from __future__ import annotations

import pytest
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
    apply_operational_sufficiency_calibration,
    build_operational_policy_prompt_hints,
    detect_operational_scenario,
    detect_over_questioning,
    detect_unnecessary_detail_request,
    detect_unnecessary_shop_identifier_request,
    evaluate_operational_sufficiency,
    has_runtime_shop_identity_context,
    is_cancellation_request_message,
    is_delivery_completed_seller_message,
    minimum_required_operational_entities,
    operational_followup_requirements,
    operationally_complete_request,
    resolve_operational_order_ids,
)
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent


def _actionability(**kwargs: object) -> ActionabilityValidationResult:
    base = {
        "actionable": True,
        "missing_required_entities": (),
        "requested_action": "update_delivery_status",
        "validation_reason": "test",
        "should_request_identifier": False,
    }
    base.update(kwargs)
    return ActionabilityValidationResult(**base)  # type: ignore[arg-type]


def test_delivery_completed_with_order_id_acknowledges_without_tracking_ask() -> None:
    seller = "سفارش با شماره 1234567 تحویل مشتری شده است"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "delivery_completed"
    )
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=("1234567",),
        )
        == ()
    )
    hints = build_operational_policy_prompt_hints(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
    )
    assert any("delivery to customer" in hint for hint in hints)
    assert any("Do not ask for tracking code" in hint for hint in hints)
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
            order_ids=("1234567",),
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "tracking_code",
                "requires_identifier_request": True,
            },
        ),
    )
    assert draft == "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    assert "رهگیری" not in draft
    assert "نحوه ارسال" not in draft


def test_reshipment_with_order_id_requires_tracking_and_shipping() -> None:
    seller = "سفارش 1234567 مجددا ارسال شد"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "shipment_reshipment"
    )
    missing = minimum_required_operational_entities(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
    )
    assert missing == ("tracking_code", "shipping_method")
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
            order_ids=("1234567",),
        ),
    )
    assert "روش ارسال" in draft
    assert "کد رهگیری پستی" in draft
    assert "در صورت وجود" in draft


def test_delivery_completed_without_order_id_requests_order_id_only() -> None:
    seller = "تحویل مشتری شده"
    assert minimum_required_operational_entities(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    ) == ("order_id",)
    followups = operational_followup_requirements(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    )
    assert followups == ("request_order_id_for_delivery_only",)
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
        ),
    )
    assert "شماره سفارش" in draft
    assert "رهگیری" not in draft


def test_shipment_with_tracking_is_operationally_complete() -> None:
    assert operationally_complete_request(
        seller_text="کد رهگیری 1234567890 برای سفارش 1234567 ارسال شد",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
        tracking_code="1234567890",
    )


def test_cancellation_with_order_id_is_acknowledge_only() -> None:
    policy_hints = build_operational_policy_prompt_hints(
        seller_text="لطفاً سفارش 7654321 را لغو کنید",
        detected_intent="general_inquiry",
        suggested_action="human_followup",
        order_ids=("7654321",),
    )
    assert any("Do not ask for cancellation reason" in hint for hint in policy_hints)
    draft = "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    result = evaluate_operational_sufficiency(
        seller_text="لطفاً سفارش 7654321 را لغو کنید",
        detected_intent="general_inquiry",
        suggested_action="human_followup",
        order_ids=("7654321",),
        draft=draft,
    )
    assert result.operationally_complete_request
    assert not result.over_questioning


def test_cancellation_without_order_id_requests_order_id_only() -> None:
    missing = minimum_required_operational_entities(
        seller_text="لطفاً سفارش را لغو کنید",
        detected_intent="general_inquiry",
        suggested_action="human_followup",
    )
    assert missing == ("order_id",)


def test_settlement_informational_does_not_require_entities() -> None:
    missing = minimum_required_operational_entities(
        seller_text="زمان تسویه چه زمانی است؟",
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
    )
    assert missing == ()
    hints = build_operational_policy_prompt_hints(
        seller_text="زمان تسویه چه زمانی است؟",
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
    )
    assert any("Do not ask for additional details" in hint for hint in hints)


def test_commission_policy_question_requires_no_order_or_tracking_entities() -> None:
    seller = "کمیسیون فروش چند درصده؟"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.COMMISSION_POLICY_QUESTION.value,
            suggested_action="answer_policy_question",
        )
        == "settlement_informational"
    )
    missing = minimum_required_operational_entities(
        seller_text=seller,
        detected_intent=VendorTicketIntent.COMMISSION_POLICY_QUESTION.value,
        suggested_action="answer_policy_question",
    )
    assert missing == ()


def test_operationally_complete_draft_strips_provide_more_details() -> None:
    draft = "درخواست لغو سفارش شما ثبت شد. لطفاً جزئیات بیشتری ارائه دهید."
    calibrated, result = apply_operational_sufficiency_calibration(
        draft,
        seller_text="لغو سفارش 1234567",
        detected_intent="general_inquiry",
        suggested_action="human_followup",
        order_ids=("1234567",),
    )
    assert "جزئیات بیشتری" not in calibrated
    assert not result.unnecessary_clarification


def test_over_questioning_detection_catches_generic_clarification() -> None:
    assert detect_unnecessary_detail_request("لطفاً مشکل را کامل توضیح دهید.")
    result = evaluate_operational_sufficiency(
        seller_text="لغو سفارش 1234567",
        detected_intent="general_inquiry",
        suggested_action="human_followup",
        order_ids=("1234567",),
        draft="لطفاً جزئیات بیشتری ارائه دهید.",
    )
    assert result.over_questioning
    assert detect_over_questioning("لطفاً جزئیات بیشتری ارائه دهید.", result)


def test_delivery_completed_over_questioning_flags_tracking_ask() -> None:
    seller = "سفارش با شماره 1234567 تحویل مشتری شده است"
    result = evaluate_operational_sufficiency(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
        draft="لطفاً کد رهگیری و نحوه ارسال را ارسال کنید.",
    )
    assert result.operationally_complete_request
    assert result.over_questioning


def test_delivery_completed_customer_phone_off_maps_to_delivery_completed() -> None:
    seller = "سلام این سفارش تحویل دادم INC-7353428 ولی مشتری گوشیش خاموشه که کد تحویل بزنم"
    assert is_delivery_completed_seller_message(seller)
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "delivery_completed"
    )
    order_ids = resolve_operational_order_ids(seller, (), scenario="delivery_completed")
    assert order_ids == ("7353428",)
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=order_ids,
        )
        == ()
    )


@pytest.mark.parametrize(
    "seller",
    (
        "سفارش شماره INC-7358055 تحویل شده لطفا اعمال بفرمایید",
        "سفارش شماره INC-7358055 تحویل شده لطفاً اعمال بفرمایید",
        "سفارش شماره INC-7358055 تحویل شد اعمال کنید",
        "سفارش شماره INC-7358055 تحویل دادم اعمال کنید",
        "سفارش شماره INC-7358055 تحویل ن شده لطفا اعمال بفرمایید",
    ),
)
def test_delivery_apply_and_typo_messages_map_to_delivery_completed(seller: str) -> None:
    assert is_delivery_completed_seller_message(seller) is True
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "delivery_completed"
    )


def test_delivery_completed_without_order_id_requests_order_id_only_even_with_code_issue() -> None:
    seller = "تحویل دادم ولی کد دریافت مشتری را ندارم"
    assert is_delivery_completed_seller_message(seller)
    missing = minimum_required_operational_entities(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    )
    assert missing == ("order_id",)
    followups = operational_followup_requirements(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
    )
    assert followups == ("request_order_id_for_delivery_only",)


def test_shipment_message_still_classified_as_shipment_reshipment() -> None:
    seller = "سفارش 7353428 ارسال شد"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "shipment_reshipment"
    )


def test_openai_prompt_distinguishes_delivered_vs_shipped() -> None:
    delivered_hints = build_operational_policy_prompt_hints(
        seller_text="سفارش با شماره 1234567 تحویل مشتری شده است",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
    )
    shipped_hints = build_operational_policy_prompt_hints(
        seller_text="سفارش 1234567 مجددا ارسال شد",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
    )
    assert any("delivery to customer" in hint for hint in delivered_hints)
    assert any("shipment/reshipment" in hint for hint in shipped_hints)

    messages = build_openai_draft_prompt(
        OpenAIDraftPromptContext(
            room_id="ROOM-1",
            seller_text="سفارش با شماره 1234567 تحویل مشتری شده است",
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            conceptual_intent_fa="ثبت تحویل",
            suggested_action="update_delivery_status",
            suggested_action_reason="test",
            ticket_label="support",
            route_label="general_vendor_support",
            order_ids=("1234567",),
            product_ids=(),
            tracking_code=None,
            knowledge_hint_document_types=(),
            actionability=_actionability(),
            target_max_chars=300,
            hard_max_chars=700,
            operational_policy_hints=delivered_hints,
        ),
    )
    combined = "\n".join(message.content for message in messages)
    assert "delivery to customer" in combined
    assert "Do not ask for tracking code" in combined


def test_cancellation_laghv_shavad_phrase() -> None:
    assert is_cancellation_request_message("سفارش 7367917 لغو شود")


def test_cancellation_without_order_id_asks_order_only() -> None:
    from app.agentic_sandbox.mock_draft_templates import (
        MockOperationalDraftInput,
        generate_mock_operational_draft,
    )

    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent="cancellation_request",
            suggested_action="human_followup",
            seller_text="لغو سفارش",
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "order_id",
                "requires_identifier_request": True,
            },
        ),
    )
    assert draft == "لطفاً شماره سفارش را ارسال کنید تا درخواست لغو بررسی شود."
    assert "دلیل" not in draft


def test_cancellation_regression_with_order_no_tracking_ask() -> None:
    seller = "سفارش 7439040 با توجه به درخواست مشتری لغو شود تقاضا لغو دارن تشکر"
    assert is_cancellation_request_message(seller)
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "cancellation_request"
    )
    order_ids = resolve_operational_order_ids(seller, ())
    assert order_ids == ("7439040",)
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=order_ids,
        )
        == ()
    )
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "tracking_code shipping_method",
                "requires_identifier_request": True,
            },
        ),
    )
    assert draft == "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    for phrase in ("روش ارسال", "کد پیگیری", "کد رهگیری", "نحوه ارسال"):
        assert phrase not in draft

    bad = "برای لغو سفارش، لطفاً روش ارسال و کد پیگیری را اعلام کنید."
    calibrated, result = apply_operational_sufficiency_calibration(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=order_ids,
    )
    assert calibrated == "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    assert result.policy.scenario == "cancellation_request"
    assert not result.over_questioning


def test_delivery_completed_regression_with_seven_digit_code() -> None:
    seller = "باسلام. کالا با کد 8057168 تحویل گیرنده شده"
    assert is_delivery_completed_seller_message(seller)
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "delivery_completed"
    )
    order_ids = resolve_operational_order_ids(seller, ())
    assert order_ids == ("8057168",)
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=order_ids,
        )
        == ()
    )
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
            actionability={
                "actionability_actionable": False,
                "actionability_missing_entities": "tracking_code shipping_method",
                "requires_identifier_request": True,
            },
        ),
    )
    assert draft == "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    for phrase in ("روش ارسال", "کد پیگیری", "کد رهگیری", "نحوه ارسال"):
        assert phrase not in draft


def test_shipment_reshipment_regression_still_requests_tracking() -> None:
    seller = "سفارش 7439040 مجددا برای مشتری ارسال شد"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "shipment_reshipment"
    )
    order_ids = resolve_operational_order_ids(seller, ())
    missing = minimum_required_operational_entities(
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=order_ids,
    )
    assert missing == ("tracking_code", "shipping_method")
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            seller_text=seller,
            order_ids=order_ids,
        ),
    )
    assert "روش ارسال" in draft
    assert "کد رهگیری پستی" in draft
    assert "در صورت وجود" in draft


def test_cancellation_wins_over_shipment_words_in_text() -> None:
    seller = "سفارش 7439040 لغو شود؛ قبلاً ارسال شده بود"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "cancellation_request"
    )
    order_ids = resolve_operational_order_ids(seller, ())
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=order_ids,
        )
        == ()
    )


def test_delivery_completed_wins_over_shipment_words_in_text() -> None:
    seller = "سفارش 8057168 تحویل گیرنده شده؛ قبلاً ارسال شده بود"
    assert (
        detect_operational_scenario(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
        )
        == "delivery_completed"
    )
    order_ids = resolve_operational_order_ids(seller, ())
    assert (
        minimum_required_operational_entities(
            seller_text=seller,
            detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
            suggested_action="update_delivery_status",
            order_ids=order_ids,
        )
        == ()
    )


def test_openai_prompt_hints_include_negative_tracking_constraints() -> None:
    cancel_hints = build_operational_policy_prompt_hints(
        seller_text="سفارش 7439040 لغو شود",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("7439040",),
    )
    delivery_hints = build_operational_policy_prompt_hints(
        seller_text="کالا با کد 8057168 تحویل گیرنده شده",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("8057168",),
    )
    shipment_hints = build_operational_policy_prompt_hints(
        seller_text="سفارش 7439040 مجددا برای مشتری ارسال شد",
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("7439040",),
    )
    assert any("NEVER ask for shipping method or tracking code" in hint for hint in cancel_hints)
    assert any("NEVER ask for shipping method or tracking code" in hint for hint in delivery_hints)
    assert any("ONLY when seller reports shipment/reshipment" in hint for hint in shipment_hints)


def test_runtime_shop_identity_context_detected_from_shop_id() -> None:
    assert has_runtime_shop_identity_context(shop_id="shop-4136") is True


def test_runtime_shop_identity_context_detected_from_session() -> None:
    assert (
        has_runtime_shop_identity_context(session_state={"manual_sandbox_shop_id": "4136"}) is True
    )


def test_unnecessary_shop_identifier_request_detected_with_runtime_context() -> None:
    draft = "برای تغییر نام فروشگاه، لطفاً شناسه فروشگاه خود را ارائه دهید."
    assert detect_unnecessary_shop_identifier_request(
        draft,
        runtime_shop_identity_available=True,
    )


def test_unnecessary_shop_identifier_request_not_detected_without_runtime_context() -> None:
    draft = "لطفاً شناسه فروشنده را وارد کنید."
    assert not detect_unnecessary_shop_identifier_request(
        draft,
        runtime_shop_identity_available=False,
    )
