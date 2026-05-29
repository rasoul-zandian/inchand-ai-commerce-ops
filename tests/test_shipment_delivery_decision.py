"""Tests for shipment/delivery operational decision layer (mocked tool results)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.operator_console.manual_chat_models import ManualChatMessage
from app.operator_console.manual_chat_sandbox import (
    _complete_seller_turn_with_reply,
)
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecisionInput,
    ShipmentDeliveryDecisionType,
    assert_safe_shipment_decision_payload,
    decide_shipment_delivery,
    is_optional_postal_tracking_request_text,
    normalize_carrier_name,
    order_is_delivered,
)

from tests.test_inchand_order_lookup import SAMPLE_ORDER_RESPONSE

_TRACKING_24 = "195370506501166594474111"
_ORDER_INC = "INC-7358954"


def _order_lookup_payload(**overrides: object) -> dict:
    from app.tools.inchand.order_lookup import parse_inchand_order_response

    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    payload = result.to_safe_dict()
    payload.update(overrides)
    return payload


def _no_parcel_tracking_payload() -> dict:
    return _order_lookup_payload(
        has_parcel_tracking_code=False,
        primary_parcel_tracking_code=None,
        is_delivered_in_inchand=False,
        order_status="در حال پردازش",
        providers=[],
        provider_count=0,
    )


def _in_transit_order_payload(*, tracking_code: str = _TRACKING_24) -> dict:
    return _order_lookup_payload(
        order_status="در حال ارسال",
        is_delivered_in_inchand=False,
        primary_provider_status="در حال ارسال",
        primary_parcel_status_name="در مسیر",
        providers=[
            {
                "shop_name": "Shop A",
                "provider_status": "در حال ارسال",
                "delivered_at": None,
                "min_delivery_date": "2026-05-31",
                "max_delivery_date": "2026-06-04",
                "parcel": {
                    "tracking_code": tracking_code,
                    "status": 2,
                    "status_name": "در مسیر",
                    "shamsi_created_at": "۱۴۰۵/۰۳/۰۴ ۰۹:۳۳",
                },
                "item_count": 1,
                "items_summary": [{"product_id": 238981, "quantity": 1}],
            },
        ],
    )


def _inp(**kwargs: object) -> ShipmentDeliveryDecisionInput:
    base = {
        "seller_text": "سلام",
        "detected_scenario": "shipment_reshipment",
        "source_mode": "manual_sandbox_chat",
        "tool_execution_mode": "manual",
    }
    base.update(kwargs)
    return ShipmentDeliveryDecisionInput(**base)


def test_no_order_id_requests_order() -> None:
    decision = decide_shipment_delivery(
        _inp(seller_text="سفارش تحویل شد", order_id=None),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.INSUFFICIENT_ORDER_IDENTIFIER
    assert decision.should_override_draft is True
    assert "شماره سفارش" in (decision.recommended_reply_fa or "")


def test_commission_policy_question_not_treated_as_shipment_missing_order_id() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="سلام وقت بخیر کمیسیون فروش چند درصده؟",
            detected_scenario="general_operational",
            order_id=None,
            ticket_label="support",
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.NOT_SHIPMENT_OR_DELIVERY_CASE
    assert decision.should_override_draft is False
    assert (decision.recommended_reply_fa or "").strip() == ""


def test_order_delivered_in_inchand_skips_iran_post() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC} تحویل شد",
            order_id=_ORDER_INC,
            order_lookup_result=_order_lookup_payload(),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND
    assert decision.skip_iran_post_verification is True
    assert "تحویل شده" in (decision.recommended_reply_fa or "")


@pytest.mark.parametrize(
    "seller_text",
    (
        "سفارش شماره INC-7358055 تحویل شده لطفا اعمال بفرمایید",
        "سفارش شماره INC-7358055 تحویل شده لطفاً اعمال بفرمایید",
        "سفارش شماره INC-7358055 تحویل شد اعمال کنید",
        "سفارش شماره INC-7358055 تحویل دادم اعمال کنید",
    ),
)
def test_delivery_apply_messages_use_delivered_lookup_reply(seller_text: str) -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=seller_text,
            detected_scenario="delivery_completed",
            order_id="INC-7358055",
            order_lookup_result=_order_lookup_payload(
                order_id="INC-7358055",
                found=True,
                is_delivered_in_inchand=True,
                order_status="تحویل شده",
            ),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND
    assert decision.should_override_draft is True
    assert decision.recommended_reply_fa == (
        "وضعیت مرسوله: تحویل شده. درخواست شما ثبت و در دست بررسی قرار گرفت."
    )


def test_delivery_apply_typo_message_still_uses_delivered_lookup_reply() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="سفارش شماره INC-7358055 تحویل ن شده لطفا اعمال بفرمایید",
            detected_scenario="general_operational",
            order_id="INC-7358055",
            order_lookup_result=_order_lookup_payload(
                order_id="INC-7358055",
                found=True,
                is_delivered_in_inchand=True,
                order_status="تحویل شده",
            ),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND
    assert decision.should_override_draft is True


def test_guarded_fallback_does_not_force_delivery_without_delivery_apply_terms() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="سلام درباره سفارش INC-7358055 سوال داشتم",
            detected_scenario="general_operational",
            order_id="INC-7358055",
            order_lookup_result=_order_lookup_payload(
                order_id="INC-7358055",
                found=True,
                is_delivered_in_inchand=True,
                order_status="تحویل شده",
            ),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.NOT_SHIPMENT_OR_DELIVERY_CASE


def test_delivered_via_provider_status_only() -> None:
    payload = _order_lookup_payload()
    payload["order_status"] = "در حال ارسال"
    payload["is_delivered_in_inchand"] = False
    payload["providers"][0]["provider_status"] = "تحویل شده"
    payload["providers"][0]["parcel"]["status_name"] = "در مسیر"
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=payload,
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND


def test_delivered_via_parcel_status_detail_name() -> None:
    payload = _order_lookup_payload()
    payload["order_status"] = "در حال ارسال"
    payload["providers"][0]["provider_status"] = "در حال ارسال"
    payload["providers"][0]["parcel"]["status_name"] = "تحویل گیرنده"
    payload["is_delivered_in_inchand"] = False
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=payload,
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND
    assert order_is_delivered(payload) is True


def test_iran_post_tracking_valid_reply() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=_in_transit_order_payload(),
            order_lookup_attempted=True,
            iran_post_tracking_result={
                "verified": True,
                "last_event_description": "تحویل به نامه رسان",
                "tracking_code": _TRACKING_24,
            },
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID
    assert "معتبر" in (decision.recommended_reply_fa or "")


def test_iran_post_tracking_invalid_reply() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=_in_transit_order_payload(),
            order_lookup_attempted=True,
            iran_post_tracking_result={"verified": False, "tracking_code": _TRACKING_24},
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_INVALID
    assert _TRACKING_24 in (decision.recommended_reply_fa or "")


def test_iran_post_needs_verification_recommendation() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=_in_transit_order_payload(),
            order_lookup_attempted=True,
            iran_post_tracking_result=None,
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_TRACKING_NEEDS_VERIFICATION
    )
    assert decision.tool_recommendations["iran_post_verification_recommended"] is True
    assert decision.should_override_draft is False


def test_non_iran_post_tracking_present() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC} با تیپاکس",
            order_id=_ORDER_INC,
            order_lookup_result=_in_transit_order_payload(tracking_code="TIPAX123456"),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.NON_IRAN_POST_TRACKING_PRESENT
    assert "تیپاکس" in (decision.recommended_reply_fa or "")


def test_missing_tracking_requests_optional_postal() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC} ارسال شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED
    reply = decision.recommended_reply_fa or ""
    assert "روش ارسال" in reply
    assert "کد رهگیری پستی" in reply
    assert "در صورت وجود" in reply


def test_optional_tracking_request_phrase_detected() -> None:
    phrase = "لطفاً روش ارسال و کد رهگیری پستی را در صورت وجود ارسال کنید."
    assert is_optional_postal_tracking_request_text(phrase) is True


def test_after_optional_ask_peyk_ack_only() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="با پیک ارسال کردم",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK
    )
    assert decision.recommended_reply_fa == "درخواست شما ثبت و در دست بررسی قرار گرفت."
    assert "کد رهگیری" not in (decision.recommended_reply_fa or "")


def test_after_optional_ask_seller_delivery_ack() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="ارسال توسط فروشنده انجام شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK
    )


def test_after_optional_ask_no_code_generic_ack() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="انجام شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.SELLER_REPLY_NO_POST_TRACKING_ACK
    assert "درخواست شما ثبت و در دست بررسی قرار گرفت." in (decision.recommended_reply_fa or "")


def test_after_optional_ask_valid_iran_post_status_and_ack() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"کد رهگیری {_TRACKING_24}",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
            seller_provided_tracking_code=_TRACKING_24,
            iran_post_tracking_result={
                "verified": True,
                "last_event_description": "تحویل به نامه رسان",
            },
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_VALID
    )
    reply = decision.recommended_reply_fa or ""
    assert "کد رهگیری پستی با موفقیت بررسی شد" in reply
    assert "تحویل به نامه رسان" in reply
    assert "درخواست شما ثبت و در دست بررسی قرار گرفت." in reply


def test_after_optional_ask_invalid_iran_post_wording() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"کد رهگیری {_TRACKING_24}",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
            seller_provided_tracking_code=_TRACKING_24,
            iran_post_tracking_result={"verified": False, "tracking_code": _TRACKING_24},
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID
    )
    reply = decision.recommended_reply_fa or ""
    assert _TRACKING_24 in reply
    assert "در صورت وجود" in reply


def test_after_optional_ask_tipax_ack_only() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="با تیپاکس ارسال شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK
    )


def test_after_optional_ask_needs_verification_not_final_invalid() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"کد رهگیری {_TRACKING_24}",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            seller_replied_after_optional_postal_tracking_request=True,
            seller_provided_tracking_code=_TRACKING_24,
            iran_post_tracking_result=None,
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_NEEDS_VERIFICATION
    )
    assert decision.tool_recommendations["iran_post_verification_recommended"] is True
    assert decision.should_override_draft is False


def test_seller_iran_post_valid_without_order_parcel() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"کد رهگیری {_TRACKING_24} سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_attempted=False,
            seller_provided_tracking_code=_TRACKING_24,
            iran_post_tracking_result={
                "verified": True,
                "last_event_description": "تحویل",
            },
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID


def test_seller_non_iran_post_ack() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text="کد رهگیری TIPAX999 سفارش INC-1111111",
            order_id="INC-1111111",
            seller_provided_tracking_code="TIPAX999",
            seller_provided_carrier="tipax",
        ),
    )
    assert (
        decision.decision_type
        == ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_IRAN_POST_TRACKING_ACK
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("پست ایران", "iran_post"),
        ("شرکت پست", "iran_post"),
        ("تیپاکس", "tipax"),
        ("ماهکس", "mahex"),
        ("چاپار", "chapar"),
        ("پیک", "peyk"),
        ("ارسال توسط فروشنده", "seller_delivery"),
        (None, "unknown"),
    ],
)
def test_carrier_normalization(raw: str | None, expected: str) -> None:
    assert normalize_carrier_name(raw) == expected


def test_decision_panel_excludes_pii() -> None:
    payload = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC}",
            order_id=_ORDER_INC,
            order_lookup_result=_order_lookup_payload(),
            order_lookup_attempted=True,
        ),
    ).to_safe_dict()
    assert_safe_shipment_decision_payload(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "receiver_name" not in blob
    assert "PRIVATE" not in blob


def test_manual_sandbox_uses_decision_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    session: dict = {}
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text=f"سلام سفارش {_ORDER_INC} تحویل شد",
            created_at="2026-01-01T00:00:00+00:00",
        ),
    ]

    def _fake_package(*_args: object, **_kwargs: object) -> object:
        from dataclasses import replace

        from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage

        from tests.test_manual_sandbox_auto_tracking import _mock_graph

        graph = replace(
            _mock_graph(draft="پیش‌نویس عمومی"),
            inchand_order_id_candidate=_ORDER_INC,
            extracted_order_ids="7358954",
        )
        return AgenticAssistedPackage(
            room_id="manual-room",
            graph=graph,
            operator_checklist=(),
            graduation_overall_status=None,
            graduation_gate_passed=False,
        )

    monkeypatch.setattr(
        "app.operator_console.manual_chat_sandbox._build_package_for_messages",
        lambda *a, **k: _fake_package(),
    )
    from app.operator_console.manual_sandbox_shipment_decision import ManualOrderLookupOutcome

    monkeypatch.setattr(
        "app.operator_console.manual_sandbox_shipment_decision.try_manual_sandbox_auto_order_lookup",
        lambda **k: ManualOrderLookupOutcome(
            payload=_order_lookup_payload(),
            auto_triggered=True,
            api_called=True,
        ),
    )

    settings = AppSettings(
        shipment_delivery_decision_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
        manual_sandbox_auto_order_lookup_enabled=True,
    )
    result = _complete_seller_turn_with_reply(
        messages,
        seller_message_id="m1",
        room_id="manual-room",
        ticket_label="shipment",
        shop_id=None,
        session_state=session,
        settings=settings,
        build_package_fn=lambda *a, **k: _fake_package(),
    )
    assert result.success is True
    assert result.used_decision_reply is True
    assert messages[-1].source == "shipment_delivery_decision"
    assert "تحویل شده" in messages[-1].text


def test_manual_sandbox_peyk_after_optional_ask_no_generic_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.operator_console.manual_sandbox_shipment_decision import (
        inchand_order_lookup_session_key,
    )

    session: dict = {}
    optional_ask = "لطفاً روش ارسال و کد رهگیری پستی را در صورت وجود ارسال کنید."
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text=f"سفارش {_ORDER_INC} ارسال شد",
            created_at="2026-01-01T00:00:00+00:00",
        ),
        ManualChatMessage(
            message_id="m2",
            sender_type="support_agent",
            text=optional_ask,
            created_at="2026-01-01T00:00:01+00:00",
            source="shipment_delivery_decision",
            is_ai_generated=True,
        ),
        ManualChatMessage(
            message_id="m3",
            sender_type="seller",
            text="با پیک ارسال کردم",
            created_at="2026-01-01T00:00:02+00:00",
        ),
    ]

    def _fake_package(*_args: object, **_kwargs: object) -> object:
        from dataclasses import replace

        from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage

        from tests.test_manual_sandbox_auto_tracking import _mock_graph

        graph = replace(
            _mock_graph(draft="پیش‌نویس عمومی که نباید نمایش داده شود"),
            inchand_order_id_candidate=_ORDER_INC,
            extracted_order_ids="7358954",
        )
        return AgenticAssistedPackage(
            room_id="manual-room",
            graph=graph,
            operator_checklist=(),
            graduation_overall_status=None,
            graduation_gate_passed=False,
        )

    monkeypatch.setattr(
        "app.operator_console.manual_chat_sandbox._build_package_for_messages",
        lambda *a, **k: _fake_package(),
    )
    session[inchand_order_lookup_session_key("manual-room")] = _no_parcel_tracking_payload()

    settings = AppSettings(
        shipment_delivery_decision_enabled=True,
        inchand_order_lookup_enabled=True,
        manual_sandbox_auto_order_lookup_enabled=False,
        manual_sandbox_auto_tracking_verify_enabled=False,
    )
    result = _complete_seller_turn_with_reply(
        messages,
        seller_message_id="m3",
        room_id="manual-room",
        ticket_label="shipment",
        shop_id=None,
        session_state=session,
        settings=settings,
        build_package_fn=lambda *a, **k: _fake_package(),
    )
    assert result.success is True
    assert result.used_decision_reply is True
    assert messages[-1].source == "shipment_delivery_decision"
    assert messages[-1].text == "درخواست شما ثبت و در دست بررسی قرار گرفت."
    assert "پیش‌نویس عمومی" not in messages[-1].text


def test_live_replay_do_not_auto_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.operator_console.manual_sandbox_shipment_decision import (
        ManualOrderLookupOutcome,
        try_manual_sandbox_auto_order_lookup,
    )

    def _lookup_result(order_id: str, **_: object) -> object:
        from app.tools.inchand.order_lookup import parse_inchand_order_response

        return parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, order_id)

    monkeypatch.setattr(
        "app.operator_console.manual_sandbox_shipment_decision.lookup_inchand_order",
        _lookup_result,
    )
    settings = AppSettings(
        manual_sandbox_auto_order_lookup_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    session: dict = {}
    manual_outcome = try_manual_sandbox_auto_order_lookup(
        order_id=_ORDER_INC,
        room_id="room",
        seller_message_id="m1",
        session_state=session,
        settings=settings,
        source_mode="manual_sandbox_chat",
        seller_text=f"سفارش {_ORDER_INC} ارسال شد",
        detected_scenario="shipment_reshipment",
    )
    assert isinstance(manual_outcome, ManualOrderLookupOutcome)
    assert manual_outcome.payload is not None
    session.clear()
    settings_replay = AppSettings(
        manual_sandbox_auto_order_lookup_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
    from app.operator_console.manual_sandbox_shipment_decision import (
        try_manual_sandbox_shipment_decision,
    )

    from tests.test_manual_sandbox_auto_tracking import _mock_graph

    package = AgenticAssistedPackage(
        room_id="room",
        graph=_mock_graph(),
        operator_checklist=(),
        graduation_overall_status=None,
        graduation_gate_passed=False,
    )
    outcome = try_manual_sandbox_shipment_decision(
        package,
        seller_text=f"سفارش {_ORDER_INC}",
        seller_message_id="m1",
        room_id="room",
        session_state=session,
        source_mode="historical_replay",
        settings=settings_replay,
    )
    assert outcome.order_lookup_stored is False


def test_no_automatic_decision_in_graph() -> None:
    from app.agentic_sandbox import agentic_graph

    source = Path(agentic_graph.__file__).read_text(encoding="utf-8")
    assert "auto-send" not in source.lower()
    assert "customer_send_allowed=True" not in source
