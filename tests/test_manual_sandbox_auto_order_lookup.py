"""Tests for controlled manual sandbox auto Inchand order lookup orchestration."""

from __future__ import annotations

import pytest
from app.agentic_sandbox.final_draft_reflection import (
    apply_final_draft_reflection_review,
)
from app.config import AppSettings
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.manual_chat_models import ManualChatMessage
from app.operator_console.manual_chat_sandbox import (
    _complete_seller_turn_with_reply,
)
from app.operator_console.manual_sandbox_shipment_decision import (
    SOURCE_MANUAL_SANDBOX_CHAT as SHIPMENT_SOURCE,
)
from app.operator_console.manual_sandbox_shipment_decision import (
    get_cached_order_lookup_by_id,
    get_orchestration_meta,
    is_manual_sandbox_auto_order_lookup_enabled,
    order_lookup_cache_bucket,
    should_trigger_manual_sandbox_auto_order_lookup,
    try_manual_sandbox_auto_order_lookup,
    try_manual_sandbox_shipment_decision,
)
from app.tools.inchand.order_lookup import assert_safe_order_lookup_payload
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecisionType,
    decide_shipment_delivery,
)

from tests.test_inchand_order_lookup import SAMPLE_ORDER_RESPONSE
from tests.test_shipment_delivery_decision import (
    _ORDER_INC,
    _inp,
    _no_parcel_tracking_payload,
    _order_lookup_payload,
)

_LOOKUP_CALLS: list[str] = []


def _fake_lookup(order_id: str, **_: object) -> object:
    from app.tools.inchand.order_lookup import parse_inchand_order_response

    _LOOKUP_CALLS.append(order_id)
    return parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, order_id)


@pytest.fixture(autouse=True)
def _clear_lookup_calls() -> None:
    _LOOKUP_CALLS.clear()


def test_is_manual_sandbox_auto_order_lookup_enabled_requires_flags() -> None:
    assert (
        is_manual_sandbox_auto_order_lookup_enabled(
            AppSettings(
                manual_sandbox_auto_order_lookup_enabled=False,
                inchand_order_lookup_enabled=True,
                inchand_api_key_value="tok",
            ),
        )
        is False
    )
    assert (
        is_manual_sandbox_auto_order_lookup_enabled(
            AppSettings(
                manual_sandbox_auto_order_lookup_enabled=True,
                inchand_order_lookup_enabled=True,
                inchand_api_key_value="tok",
            ),
        )
        is True
    )


def test_auto_lookup_trigger_only_manual_sandbox_with_order_id() -> None:
    settings = AppSettings(
        manual_sandbox_auto_order_lookup_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    assert should_trigger_manual_sandbox_auto_order_lookup(
        source_mode=SHIPMENT_SOURCE,
        order_id=_ORDER_INC,
        seller_text=f"سفارش {_ORDER_INC} ارسال شد",
        detected_scenario="shipment_reshipment",
        settings=settings,
    )
    assert not should_trigger_manual_sandbox_auto_order_lookup(
        source_mode="historical_replay",
        order_id=_ORDER_INC,
        seller_text=f"سفارش {_ORDER_INC} ارسال شد",
        detected_scenario="shipment_reshipment",
        settings=settings,
    )


def test_cache_hit_prevents_duplicate_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.operator_console.manual_sandbox_shipment_decision.lookup_inchand_order",
        _fake_lookup,
    )
    session: dict = {}
    settings = AppSettings(
        manual_sandbox_auto_order_lookup_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    first = try_manual_sandbox_auto_order_lookup(
        order_id=_ORDER_INC,
        room_id="room-1",
        seller_message_id="m1",
        session_state=session,
        settings=settings,
        seller_text=f"سفارش {_ORDER_INC} ارسال شد",
        detected_scenario="shipment_reshipment",
    )
    second = try_manual_sandbox_auto_order_lookup(
        order_id=_ORDER_INC,
        room_id="room-1",
        seller_message_id="m2",
        session_state=session,
        settings=settings,
        seller_text=f"سفارش {_ORDER_INC} وضعیت؟",
        detected_scenario="shipment_reshipment",
    )
    assert first.api_called is True
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.api_called is False
    assert len(_LOOKUP_CALLS) == 1
    assert get_cached_order_lookup_by_id(session, _ORDER_INC) is not None


def test_delivery_completed_without_tracking_no_tracking_ask() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC} تحویل شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            detected_scenario="delivery_completed",
        ),
    )
    assert decision.decision_type == (
        ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK
    )
    reply = decision.recommended_reply_fa or ""
    assert "درخواست تحویل سفارش" in reply
    assert "کد رهگیری پستی" not in reply
    assert decision.skip_iran_post_verification is True


def test_shipment_without_tracking_asks_optional_tracking() -> None:
    decision = decide_shipment_delivery(
        _inp(
            seller_text=f"سفارش {_ORDER_INC} ارسال شد",
            order_id=_ORDER_INC,
            order_lookup_result=_no_parcel_tracking_payload(),
            order_lookup_attempted=True,
            detected_scenario="shipment_reshipment",
        ),
    )
    assert decision.decision_type == ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED
    assert "در صورت وجود" in (decision.recommended_reply_fa or "")


def test_delivered_order_skips_iran_post_in_decision() -> None:
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


def test_session_cache_stores_safe_payload_only() -> None:
    payload = _no_parcel_tracking_payload()
    assert_safe_order_lookup_payload(payload)
    session: dict = {}
    bucket = order_lookup_cache_bucket(session)
    bucket[_ORDER_INC] = payload
    cached = get_cached_order_lookup_by_id(session, _ORDER_INC)
    assert cached is not None
    assert "receiver_name" not in cached


def test_live_replay_never_auto_lookup() -> None:
    from tests.test_manual_sandbox_auto_tracking import _mock_graph

    session: dict = {}
    package = AgenticAssistedPackage(
        room_id="room",
        graph=_mock_graph(),
        operator_checklist=(),
        graduation_overall_status=None,
        graduation_gate_passed=False,
    )
    settings = AppSettings(
        manual_sandbox_auto_order_lookup_enabled=True,
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
        shipment_delivery_decision_enabled=True,
    )
    outcome = try_manual_sandbox_shipment_decision(
        package,
        seller_text=f"سفارش {_ORDER_INC}",
        seller_message_id="m1",
        room_id="room",
        session_state=session,
        source_mode="historical_replay",
        settings=settings,
    )
    assert outcome.order_lookup_auto_triggered is False


def test_manual_session_lookup_source_not_graph_auto() -> None:
    from app.operator_console.manual_sandbox_shipment_decision import (
        inchand_order_lookup_session_key,
    )

    from tests.test_manual_sandbox_auto_tracking import _mock_graph

    session: dict = {}
    session[inchand_order_lookup_session_key("room")] = _order_lookup_payload(order_id=_ORDER_INC)
    package = AgenticAssistedPackage(
        room_id="room",
        graph=_mock_graph(),
        operator_checklist=(),
        graduation_overall_status=None,
        graduation_gate_passed=False,
    )
    settings = AppSettings(shipment_delivery_decision_enabled=True)
    _ = try_manual_sandbox_shipment_decision(
        package,
        seller_text=f"سفارش {_ORDER_INC} تحویل شده لطفا اعمال کنید",
        seller_message_id="m1",
        room_id="room",
        session_state=session,
        source_mode=SHIPMENT_SOURCE,
        settings=settings,
        ticket_label="shipment",
    )
    meta = get_orchestration_meta(session)
    assert meta.get("order_lookup_result_source") in {"manual_button", "session_cache"}
    assert meta.get("order_lookup_result_source") != "graph_auto"


def test_protected_delivery_completed_reply_survives_reflection() -> None:
    from app.workflows.shipment_delivery_decision import ShipmentDeliveryDecision

    protected = "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    decision = ShipmentDeliveryDecision(
        decision_type=ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK,
        recommended_reply_fa=protected,
        should_override_draft=True,
    )
    final, result = apply_final_draft_reflection_review(
        protected,
        seller_text=f"سفارش {_ORDER_INC} تحویل شد",
        order_ids=(_ORDER_INC.split("-")[1],),
        shipment_delivery_decision=decision,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert final == protected
    assert "کد رهگیری" not in final


def test_manual_sandbox_orchestration_uses_decision_not_generic_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session: dict = {}
    from app.operator_console.manual_sandbox_shipment_decision import (
        inchand_order_lookup_session_key,
    )

    session[inchand_order_lookup_session_key("manual-room")] = _no_parcel_tracking_payload()

    def _fake_package(*_args: object, **_kwargs: object) -> AgenticAssistedPackage:
        from dataclasses import replace

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
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text=f"سفارش {_ORDER_INC} ارسال شد",
            created_at="2026-01-01T00:00:00+00:00",
        ),
    ]
    settings = AppSettings(
        shipment_delivery_decision_enabled=True,
        manual_sandbox_auto_order_lookup_enabled=False,
        manual_sandbox_auto_tracking_verify_enabled=False,
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
    assert "در صورت وجود" in messages[-1].text
