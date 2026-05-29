"""Synthetic shipment/delivery decision scenarios with mocked Inchand/Iran Post results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.multi_turn_eval_runner import load_eval_scenarios
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecisionInput,
    ShipmentDeliveryDecisionType,
    decide_shipment_delivery,
)

from tests.test_shipment_delivery_decision import (
    _in_transit_order_payload,
    _no_parcel_tracking_payload,
    _order_lookup_payload,
)

_TRACKING_24 = "195370506501166594474111"
_ORDER_INC = "INC-7358954"

_SCENARIO_FIXTURES: dict[str, dict] = {
    "delivered_order_skips_iran_post_verification": {
        "order_lookup": _order_lookup_payload(),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.ORDER_ALREADY_DELIVERED_IN_INCHAND,
        "skip_iran_post": True,
    },
    "order_tracking_iran_post_valid": {
        "order_lookup": _in_transit_order_payload(),
        "iran_post": {"verified": True, "last_event_description": "تحویل"},
        "expected_type": ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_VALID,
    },
    "order_tracking_iran_post_invalid": {
        "order_lookup": _in_transit_order_payload(),
        "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
        "expected_type": ShipmentDeliveryDecisionType.IRAN_POST_TRACKING_INVALID,
    },
    "order_tracking_missing_requests_optional_tracking": {
        "order_lookup": _order_lookup_payload(
            has_parcel_tracking_code=False,
            primary_parcel_tracking_code=None,
            is_delivered_in_inchand=False,
            order_status="در حال پردازش",
            providers=[],
            provider_count=0,
        ),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED,
    },
    "non_iran_post_tracking_present_ack": {
        "order_lookup": _in_transit_order_payload(tracking_code="TIPAX999"),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.NON_IRAN_POST_TRACKING_PRESENT,
    },
    "optional_tracking_request_seller_no_code_ack": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK,
        "seller_replied_after_optional": True,
    },
    "optional_tracking_request_invalid_post_code": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID,
        "seller_replied_after_optional": True,
        "seller_provided_tracking_code": _TRACKING_24,
    },
    "optional_tracking_request_valid_post_code": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": {"verified": True, "last_event_description": "تحویل"},
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_VALID,
        "seller_replied_after_optional": True,
        "seller_provided_tracking_code": _TRACKING_24,
    },
    "delivered_without_tracking_ack": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.DELIVERY_COMPLETED_WITHOUT_TRACKING_ACK,
        "detected_scenario": "delivery_completed",
    },
    "shipment_without_tracking_optional_request": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.TRACKING_MISSING_REQUEST_REQUIRED,
        "detected_scenario": "shipment_reshipment",
    },
    "shipment_optional_tracking_peyk_ack": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": None,
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_NON_POST_OR_NO_TRACKING_ACK,
        "seller_replied_after_optional": True,
    },
    "shipment_optional_tracking_valid_post": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": {"verified": True, "last_event_description": "تحویل"},
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_VALID,
        "seller_replied_after_optional": True,
        "seller_provided_tracking_code": _TRACKING_24,
    },
    "shipment_optional_tracking_invalid_post": {
        "order_lookup": _no_parcel_tracking_payload(),
        "iran_post": {"verified": False, "tracking_code": _TRACKING_24},
        "expected_type": ShipmentDeliveryDecisionType.SELLER_PROVIDED_IRAN_POST_TRACKING_INVALID,
        "seller_replied_after_optional": True,
        "seller_provided_tracking_code": _TRACKING_24,
    },
}


@pytest.mark.parametrize("scenario_id", list(_SCENARIO_FIXTURES.keys()))
def test_decision_eval_scenario_fixtures(scenario_id: str) -> None:
    scenarios = {
        item.scenario_id: item
        for item in load_eval_scenarios(
            Path(__file__).resolve().parents[1] / "data/evals/multi_turn_scenarios.json",
        )
    }
    assert scenario_id in scenarios
    seller_text = scenarios[scenario_id].messages[-1].text
    fixture = _SCENARIO_FIXTURES[scenario_id]
    decision = decide_shipment_delivery(
        ShipmentDeliveryDecisionInput(
            seller_text=seller_text,
            detected_scenario=str(fixture.get("detected_scenario") or "shipment_reshipment"),
            order_id=_ORDER_INC,
            order_lookup_result=fixture["order_lookup"],
            order_lookup_attempted=True,
            iran_post_tracking_result=fixture.get("iran_post"),
            seller_provided_tracking_code=fixture.get("seller_provided_tracking_code"),
            seller_replied_after_optional_postal_tracking_request=bool(
                fixture.get("seller_replied_after_optional"),
            ),
            source_mode="manual_sandbox_chat",
            tool_execution_mode="manual",
            ticket_label="shipment",
        ),
    )
    assert decision.decision_type == fixture["expected_type"]
    if fixture.get("skip_iran_post"):
        assert decision.skip_iran_post_verification is True
    assert json.dumps(decision.to_safe_dict(), ensure_ascii=False)
