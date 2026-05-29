"""Tests for Inchand order lookup tool (mock HTTP; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.tools.inchand.order_lookup import (
    InchandOrderLookupError,
    assert_private_order_raw_output_path,
    assert_safe_order_lookup_payload,
    build_inchand_order_lookup_recommendation_metadata,
    build_order_lookup_headers,
    build_order_lookup_url,
    is_delivered_order_state,
    looks_like_inchand_order_id,
    lookup_inchand_order,
    normalize_inchand_order_id,
    parse_inchand_order_response,
)
from app.workflows.multi_turn_ticket_context import multi_turn_context_metadata_row

from tests.test_multi_turn_ticket_context import _message, _snapshot

_ORDER_7 = "7358954"
_ORDER_INC = "INC-7358954"
_TRACKING_24 = "195370506501166594474111"


SAMPLE_ORDER_RESPONSE = {
    "data": {
        "id": 1284835,
        "user_id": 969659,
        "order_status": "تحویل شده",
        "payment_status": "موفق",
        "tracking_code": "INC-7358954",
        "providers": [
            {
                "shop_name": "Shop A",
                "status": "تحویل شده",
                "shipping_price": 199000,
                "min_delivery_date": "2026-05-31",
                "max_delivery_date": "2026-06-04",
                "delivered_at": "2026-05-26 09:33:15",
                "parcel": {
                    "sender_name": "PRIVATE SENDER",
                    "receiver_name": "PRIVATE RECEIVER",
                    "tracking_code": _TRACKING_24,
                    "status_detail": {
                        "name": "تحویل مشتری",
                        "color": "emerald",
                        "code": 1,
                    },
                    "status": 1,
                    "shamsi_created_at": "۱۴۰۵/۰۳/۰۴ ۰۹:۳۳",
                },
                "items": [
                    {
                        "product_id": 238981,
                        "product_name": "Secret Product",
                        "quantity": 1,
                    },
                ],
            },
        ],
        "created_at": "2026-05-22T10:34:09.000000Z",
    },
}

SAMPLE_ORDER_DIRECT_RESPONSE = dict(SAMPLE_ORDER_RESPONSE["data"])


def test_normalize_seven_digit_to_inc() -> None:
    assert normalize_inchand_order_id(_ORDER_7) == _ORDER_INC


def test_normalize_inc_lowercase() -> None:
    assert normalize_inchand_order_id("inc-7358954") == _ORDER_INC


def test_reject_24_digit_tracking_as_order_id() -> None:
    assert normalize_inchand_order_id(_TRACKING_24) == ""
    assert looks_like_inchand_order_id(_TRACKING_24) is False


def test_build_order_lookup_url() -> None:
    settings = AppSettings(inchand_api_base_url="https://app.inchand.com/api/v1/internal")
    url = build_order_lookup_url(_ORDER_INC, settings)
    assert url == "https://app.inchand.com/api/v1/internal/orders/INC-7358954"


def test_headers_use_authorization_token() -> None:
    settings = AppSettings(
        inchand_api_key_name="Authorization",
        inchand_api_key_value="secret-token",
    )
    headers = build_order_lookup_headers(settings)
    assert headers["Authorization"] == "secret-token"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Requested-With"] == "XMLHttpRequest"


def test_headers_fallback_live_rooms_token() -> None:
    settings = AppSettings(
        inchand_api_key_value=None,
        live_rooms_api_token="rooms-token",
    )
    headers = build_order_lookup_headers(settings)
    assert headers["Authorization"] == "rooms-token"


def test_parse_sample_response() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    assert result.found is True
    assert result.order_id == _ORDER_INC
    assert result.order_status == "تحویل شده"
    assert result.has_parcel_tracking_code is True
    assert result.primary_parcel_tracking_code == _TRACKING_24


def test_parse_sample_direct_object_response() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_DIRECT_RESPONSE, _ORDER_INC)
    assert result.found is True
    assert result.order_id == _ORDER_INC
    assert result.order_status == "تحویل شده"
    assert result.provider_count == 1
    assert result.primary_parcel_tracking_code == _TRACKING_24
    assert result.primary_provider_status == "تحویل شده"
    assert result.primary_parcel_status_name == "تحویل مشتری"
    assert result.is_delivered_in_inchand is True
    assert "تحویل" in (result.safe_summary_fa or "")


def test_safe_output_excludes_pii() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    payload = result.to_safe_dict()
    assert_safe_order_lookup_payload(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "user_id" not in blob
    assert "receiver_name" not in blob
    assert "sender_name" not in blob
    assert "PRIVATE" not in blob
    assert "Secret Product" not in blob
    assert "product_name" not in blob


def test_direct_object_safe_output_excludes_pii() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_DIRECT_RESPONSE, _ORDER_INC)
    payload = result.to_safe_dict()
    assert_safe_order_lookup_payload(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "user_id" not in blob
    assert "receiver_name" not in blob
    assert "sender_name" not in blob
    assert "PRIVATE" not in blob
    assert "Secret Product" not in blob
    assert "product_name" not in blob


def test_parse_missing_response_returns_not_found() -> None:
    result = parse_inchand_order_response({}, _ORDER_INC)
    assert result.found is False
    assert result.error_type == "not_found"


def test_has_parcel_tracking_code() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    assert result.has_parcel_tracking_code is True
    assert result.primary_parcel_tracking_code == _TRACKING_24


def test_delivered_via_provider_status() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    assert result.is_delivered_in_inchand is True
    assert is_delivered_order_state(result) is True


def test_delivered_via_parcel_status_detail() -> None:
    response = {
        "data": {
            **SAMPLE_ORDER_RESPONSE["data"],
            "order_status": "در حال ارسال",
            "providers": [
                {
                    **SAMPLE_ORDER_RESPONSE["data"]["providers"][0],
                    "status": "در حال ارسال",
                    "parcel": {
                        **SAMPLE_ORDER_RESPONSE["data"]["providers"][0]["parcel"],
                        "status_detail": {"name": "تحویل گیرنده", "code": 1},
                    },
                },
            ],
        },
    }
    result = parse_inchand_order_response(response, _ORDER_INC)
    assert result.is_delivered_in_inchand is True
    assert result.delivery_source == "parcel_status_detail"


def test_raw_output_path_must_be_private(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="data/private"):
        assert_private_order_raw_output_path(tmp_path / "reports" / "raw.json")
    private = tmp_path / "data" / "private" / "raw.json"
    assert assert_private_order_raw_output_path(private) == private.resolve()


def test_lookup_mock_http() -> None:
    def _mock_get(_url: str, _headers: dict[str, str], _timeout: float) -> dict:
        return SAMPLE_ORDER_RESPONSE

    settings = AppSettings(
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    result = lookup_inchand_order(_ORDER_7, settings=settings, http_client=_mock_get)
    assert result.found is True
    assert result.order_id == _ORDER_INC
    assert result.error_type is None


def test_lookup_disabled() -> None:
    settings = AppSettings(inchand_order_lookup_enabled=False, inchand_api_key_value="tok")
    result = lookup_inchand_order(_ORDER_INC, settings=settings)
    assert result.error_type == "disabled"


def test_recommendation_metadata_when_order_extracted() -> None:
    meta = build_inchand_order_lookup_recommendation_metadata(
        order_ids=(_ORDER_7,),
        seller_text="سفارش INC-7358954",
    )
    assert meta["inchand_order_lookup_recommended"] is True
    assert meta["inchand_order_id_candidate"] == _ORDER_INC


def test_multi_turn_metadata_includes_order_lookup_recommendation() -> None:
    from app.workflows.multi_turn_ticket_context import build_multi_turn_context

    snapshot = _snapshot(
        [
            _message("1", "seller", "سفارش 7358954 تحویل نشده"),
        ],
    )
    ctx = build_multi_turn_context(
        snapshot,
        settings=AppSettings(multi_turn_context_enabled=True),
    )
    meta = multi_turn_context_metadata_row(ctx)
    assert meta.get("inchand_order_lookup_recommended") is True
    assert meta.get("inchand_order_id_candidate") == _ORDER_INC


def test_no_automatic_api_call_in_graph() -> None:
    from app.agentic_sandbox import agentic_graph

    source = Path(agentic_graph.__file__).read_text(encoding="utf-8")
    assert "execute_order_lookup" in source
    assert "manual_trigger" not in source


def test_cli_writes_safe_summary_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    summary_path = tmp_path / "reports" / "inchand_order_lookup_summary.json"
    private_raw = tmp_path / "data" / "private" / "raw.json"

    def _mock_get(_url: str, _headers: dict[str, str], _timeout: float) -> dict:
        return SAMPLE_ORDER_RESPONSE

    monkeypatch.setenv("INCHAND_ORDER_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("INCHAND_API_KEY_VALUE", "tok")
    monkeypatch.setattr(
        "app.tools.inchand.order_lookup.http_get_order_json",
        _mock_get,
    )

    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "lookup_inchand_order.py"
    spec = importlib.util.spec_from_file_location("lookup_inchand_order_cli", script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    rc = cli.main(
        [
            "--order-id",
            _ORDER_7,
            "--summary-output",
            str(summary_path),
            "--raw-private-output",
            str(private_raw),
            "--no-raw",
            "--overwrite",
        ],
    )
    assert rc == 0
    assert summary_path.is_file()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert_safe_order_lookup_payload(payload)
    assert not private_raw.exists()


def test_session_safe_dict_excludes_pii() -> None:
    result = parse_inchand_order_response(SAMPLE_ORDER_RESPONSE, _ORDER_INC)
    payload = result.to_safe_dict()
    assert_safe_order_lookup_payload(payload)
    assert "receiver_name" not in json.dumps(payload)


def test_http_error_propagates() -> None:
    def _error(_url: str, _headers: dict[str, str], _timeout: float) -> dict:
        raise InchandOrderLookupError(error_type="http_error", error_message="500")

    settings = AppSettings(
        inchand_order_lookup_enabled=True,
        inchand_api_key_value="tok",
    )
    result = lookup_inchand_order(_ORDER_INC, settings=settings, http_client=_error)
    assert result.error_type == "http_error"
