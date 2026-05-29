"""Tests for multi-order shipment/delivery batch handling."""

from __future__ import annotations

from app.config import AppSettings
from app.workflows.multi_order_shipment_decision import (
    MultiOrderShipmentInput,
    decide_multi_order_shipment,
    extract_all_inchand_order_ids,
    extract_all_inchand_order_ids_with_diagnostics,
)


def _delivered_lookup(order_id: str) -> dict[str, object]:
    return {
        "order_id": order_id,
        "found": True,
        "is_delivered_in_inchand": True,
        "order_status": "تحویل شده",
        "primary_provider_status": "تحویل شده",
        "primary_parcel_status_name": "تحویل مشتری",
        "primary_parcel_tracking_code": None,
    }


def _not_found_lookup(order_id: str) -> dict[str, object]:
    return {
        "order_id": order_id,
        "found": False,
        "is_delivered_in_inchand": False,
        "error_type": "not_found",
    }


def _no_tracking_lookup(order_id: str) -> dict[str, object]:
    return {
        "order_id": order_id,
        "found": True,
        "is_delivered_in_inchand": False,
        "order_status": "در حال پردازش",
        "primary_provider_status": None,
        "primary_parcel_status_name": None,
        "primary_parcel_tracking_code": None,
    }


def test_extract_multiple_inc_order_ids_preserves_order() -> None:
    text = "INC-7357421، INC-7358055، INC-7358032، INC-7358099"
    assert extract_all_inchand_order_ids(text) == [
        "INC-7357421",
        "INC-7358055",
        "INC-7358032",
        "INC-7358099",
    ]


def test_extract_deduplicates_and_rejects_tracking_code() -> None:
    text = "INC-7358055 و inc-7358055 و 195370506501166594474111"
    diag = extract_all_inchand_order_ids_with_diagnostics(text)
    assert list(diag.normalized_order_ids) == ["INC-7358055"]
    assert diag.duplicate_count == 1
    assert "195370506501166594474111" in diag.rejected_candidates


def test_two_delivered_orders_returns_all_delivered_reply() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="سفارش‌های INC-7358055 و INC-7357421 تحویل شده لطفا اعمال کنید",
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            preloaded_lookup_results={
                "INC-7358055": _delivered_lookup("INC-7358055"),
                "INC-7357421": _delivered_lookup("INC-7357421"),
            },
            settings=AppSettings(),
        ),
    )
    assert decision.decision_type == "multi_order_all_delivered"
    assert "تحویل شده" in decision.recommended_reply_fa


def test_mixed_delivered_not_found_returns_mixed_reply() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="INC-7358055 و INC-7357421 تحویل شده لطفا اعمال",
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            preloaded_lookup_results={
                "INC-7358055": _delivered_lookup("INC-7358055"),
                "INC-7357421": _not_found_lookup("INC-7357421"),
            },
            settings=AppSettings(),
        ),
    )
    assert decision.decision_type == "multi_order_not_found_present"
    assert "یافت نشدند" in decision.recommended_reply_fa


def test_delivery_completed_no_tracking_does_not_ask_tracking() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="سفارش‌های INC-7358055 و INC-7357421 تحویل شده لطفا اعمال",
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            preloaded_lookup_results={
                "INC-7358055": _no_tracking_lookup("INC-7358055"),
                "INC-7357421": _no_tracking_lookup("INC-7357421"),
            },
            settings=AppSettings(),
        ),
    )
    assert "کد رهگیری" not in decision.recommended_reply_fa


def test_shipment_no_tracking_asks_optional_tracking() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="سفارش‌های INC-7358055 و INC-7357421 ارسال شد",
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            preloaded_lookup_results={
                "INC-7358055": _no_tracking_lookup("INC-7358055"),
                "INC-7357421": _no_tracking_lookup("INC-7357421"),
            },
            settings=AppSettings(),
        ),
    )
    assert decision.decision_type == "multi_order_shipment_tracking_missing"
    assert "کد رهگیری پستی" in decision.recommended_reply_fa


def test_limit_exceeded_returns_compact_registration_reply() -> None:
    settings = AppSettings(
        multi_order_batch_enabled=True,
        multi_order_batch_max_auto_lookup=5,
    )
    text = " ".join([f"INC-73580{i:02d}" for i in range(1, 7)])
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text=text,
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            settings=settings,
        ),
    )
    assert decision.summary.limit_exceeded is True
    assert decision.decision_type == "multi_order_limit_exceeded"


def test_live_source_batch_auto_lookup_blocked() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="INC-7358055 و INC-7357421 تحویل شده",
            source_mode="live_api_feed",
            graph_tools_enabled=True,
            settings=AppSettings(),
        ),
    )
    assert decision.decision_type == "multi_order_mixed_review"
    assert all(row.lookup_error_type for row in decision.per_order)


def test_per_order_safe_payload_excludes_pii() -> None:
    decision = decide_multi_order_shipment(
        MultiOrderShipmentInput(
            seller_text="INC-7358055 و INC-7357421 تحویل شده",
            source_mode="manual_sandbox_chat",
            graph_tools_enabled=True,
            preloaded_lookup_results={
                "INC-7358055": {
                    **_delivered_lookup("INC-7358055"),
                    "receiver_name": "PRIVATE",
                },
                "INC-7357421": _delivered_lookup("INC-7357421"),
            },
            settings=AppSettings(),
        ),
    )
    row = decision.per_order[0].to_safe_dict()
    assert "receiver_name" not in row
