"""Tests for Iran Post tracking verification tool (mock HTTP; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.tools.tracking.iran_post_tracking import (
    IranPostTrackingError,
    assert_private_raw_output_path,
    assert_safe_tracking_result_payload,
    build_iran_post_request_payload,
    build_tracking_verification_chat_reply,
    build_tracking_verification_recommendation_metadata,
    compute_tracking_verification_recommendation,
    looks_like_iran_post_tracking_code,
    normalize_tracking_code,
    parse_iran_post_event_description,
    parse_iran_post_response,
    verify_iran_post_tracking_code,
)
from app.workflows.multi_turn_ticket_context import (
    PendingRequestType,
    multi_turn_context_metadata_row,
)

from tests.test_multi_turn_ticket_context import _message, _snapshot

_TRACKING_24 = "051800506400081160839102"
_ORDER_7 = "7367917"


def test_normalize_tracking_code_strips_separators() -> None:
    raw = "0518 0050-6400081160839102"
    assert normalize_tracking_code(raw) == _TRACKING_24


def test_24_digit_code_plausible() -> None:
    plausible, warning = looks_like_iran_post_tracking_code(_TRACKING_24)
    assert plausible is True
    assert warning is None


def test_7_digit_order_id_rejected() -> None:
    plausible, warning = looks_like_iran_post_tracking_code(_ORDER_7)
    assert plausible is False
    assert warning == "too_short_for_iran_post"


def test_default_settings_use_package_number_field() -> None:
    settings = AppSettings()
    assert settings.iran_post_tracking_code_field == "PackageNumber"


def test_request_payload_default_uses_package_number() -> None:
    payload, params = build_iran_post_request_payload(_TRACKING_24, "secret-token")
    assert payload["Identity"]["Token"] == "secret-token"
    assert params["PackageNumber"] == _TRACKING_24
    assert params["TraceNumber"] == ""


def test_request_payload_trace_number_when_configured() -> None:
    _, params = build_iran_post_request_payload(
        _TRACKING_24,
        "secret-token",
        code_field="TraceNumber",
    )
    assert params["TraceNumber"] == _TRACKING_24
    assert params["PackageNumber"] == ""


def _success_response(*, events: list[dict[str, str]] | None = None) -> dict:
    return {
        "Status": {"Code": "0", "Description": "OK"},
        "Parameters": {
            "AcceptanceDateTime": "2024-01-01T10:00:00",
            "Destination": "Tehran",
            "Source": "Isfahan",
            "ServiceType": "ordinary",
            "Weight": "500g",
            "ReceiverName": "PRIVATE",
            "SenderName": "PRIVATE",
            "PostPackageStatusDetail": events or [],
        },
    }


def test_parse_success_response_with_events() -> None:
    response = _success_response(
        events=[
            {
                "DateTime": "2024-01-02",
                "EventNumber": "1",
                "ExtraInfo": "accepted",
                "Province": "Tehran",
            },
        ],
    )
    result = parse_iran_post_response(response, _TRACKING_24)
    assert result.verified is True
    assert result.event_count == 1
    assert result.last_event_province == "Tehran"
    assert "ReceiverName" not in result.to_safe_dict()


def test_parse_response_with_empty_events() -> None:
    response = _success_response(events=[])
    response["Parameters"]["AcceptanceDateTime"] = "2024-01-01"
    result = parse_iran_post_response(response, _TRACKING_24)
    assert result.verified is True
    assert result.event_count == 0


def test_parse_failure_status() -> None:
    response = {
        "Status": {"Code": "error", "Description": "not found"},
        "Parameters": {},
    }
    result = parse_iran_post_response(response, _TRACKING_24)
    assert result.verified is False


def test_http_timeout_handled() -> None:
    def _timeout(_url: str, _payload: object, _timeout: float) -> dict:
        raise IranPostTrackingError(error_type="timeout", error_message="timed out")

    settings = AppSettings(
        iran_post_tracking_enabled=True,
        iran_post_tracking_token="tok",
    )
    result = verify_iran_post_tracking_code(
        _TRACKING_24,
        settings=settings,
        http_client=_timeout,
    )
    assert result.error_type == "timeout"
    assert result.verified is False


def test_raw_output_path_must_be_private(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="data/private"):
        assert_private_raw_output_path(tmp_path / "reports" / "raw.json")
    private = tmp_path / "data" / "private" / "raw.json"
    assert assert_private_raw_output_path(private) == private.resolve()


def test_session_safe_dict_excludes_pii() -> None:
    response = _success_response(
        events=[{"DateTime": "t", "ExtraInfo": "x", "Province": "p"}],
    )
    payload = parse_iran_post_response(response, _TRACKING_24).to_safe_dict()
    assert_safe_tracking_result_payload(payload)
    blob = json.dumps(payload)
    assert "ReceiverName" not in blob
    assert "SenderName" not in blob
    assert "PRIVATE" not in blob


def test_recommendation_metadata_when_pending_tracking_fulfilled() -> None:
    meta = build_tracking_verification_recommendation_metadata(
        pending_request_type=PendingRequestType.REQUESTED_TRACKING_CODE.value,
        pending_request_fulfilled=True,
        tracking_codes=(_TRACKING_24,),
    )
    assert meta["tracking_verification_recommended"] is True
    assert meta["tracking_verification_carrier_candidate"] == "iran_post"


def test_recommendation_not_set_for_unfulfilled() -> None:
    assert (
        compute_tracking_verification_recommendation(
            pending_request_type=PendingRequestType.REQUESTED_TRACKING_CODE.value,
            pending_request_fulfilled=False,
            tracking_code=_TRACKING_24,
        )
        is False
    )


def test_multi_turn_metadata_includes_recommendation() -> None:
    from app.config import AppSettings
    from app.workflows.multi_turn_ticket_context import build_multi_turn_context

    snapshot = _snapshot(
        [
            _message("1", "support_agent", "لطفاً کد رهگیری را ارسال کنید"),
            _message("2", "seller", _TRACKING_24),
        ],
    )
    ctx = build_multi_turn_context(
        snapshot,
        settings=AppSettings(multi_turn_context_enabled=True),
    )
    meta = multi_turn_context_metadata_row(ctx)
    assert meta.get("tracking_verification_recommended") is True


def test_no_automatic_api_call_in_graph() -> None:
    from app.agentic_sandbox import agentic_graph

    source = Path(agentic_graph.__file__).read_text(encoding="utf-8")
    assert "execute_iran_post_tracking" in source
    assert "manual_trigger" not in source


def test_verify_mock_http_success() -> None:
    def _mock_post(_url: str, _payload: object, _timeout: float) -> dict:
        return _success_response(
            events=[{"DateTime": "t", "ExtraInfo": "delivered", "Province": "Tehran"}],
        )

    settings = AppSettings(
        iran_post_tracking_enabled=True,
        iran_post_tracking_token="tok",
    )
    result = verify_iran_post_tracking_code(
        _TRACKING_24,
        settings=settings,
        http_client=_mock_post,
    )
    assert result.verified is True
    assert result.error_type is None


def test_verify_disabled_without_token() -> None:
    settings = AppSettings(iran_post_tracking_enabled=False)
    result = verify_iran_post_tracking_code(_TRACKING_24, settings=settings)
    assert result.error_type == "disabled"


_JSON_EXTRA = '{"شرح":"مرسوله  تحویل گیرنده گردیده است ","نامه رسان":"زهرا یاسری فرد"}'
_CARRIER_NAME = "زهرا یاسری فرد"
_CLEAN_DESCRIPTION = "مرسوله تحویل گیرنده گردیده است"


def test_parse_json_extra_info_returns_sharh_only() -> None:
    assert parse_iran_post_event_description(_JSON_EXTRA) == _CLEAN_DESCRIPTION


def test_parse_json_extra_info_hides_mail_carrier_name() -> None:
    parsed = parse_iran_post_event_description(_JSON_EXTRA)
    assert _CARRIER_NAME not in parsed
    response = _success_response(
        events=[{"DateTime": "t", "ExtraInfo": _JSON_EXTRA, "Province": "تهران"}],
    )
    result = parse_iran_post_response(response, _TRACKING_24)
    blob = json.dumps(result.to_safe_dict(), ensure_ascii=False)
    assert _CARRIER_NAME not in blob
    assert "نامه رسان" not in blob
    assert result.last_event_description == _CLEAN_DESCRIPTION


def test_parse_plain_text_extra_info() -> None:
    assert parse_iran_post_event_description("accepted   event") == "accepted event"
    response = _success_response(
        events=[{"DateTime": "t", "ExtraInfo": "accepted   event", "Province": "Tehran"}],
    )
    result = parse_iran_post_response(response, _TRACKING_24)
    assert result.events[0].description == "accepted event"


def test_safe_summary_uses_clean_event_description() -> None:
    response = _success_response(
        events=[{"DateTime": "t", "ExtraInfo": _JSON_EXTRA, "Province": "تهران"}],
    )
    result = parse_iran_post_response(response, _TRACKING_24)
    assert _CLEAN_DESCRIPTION in (result.safe_summary_fa or "")
    assert _JSON_EXTRA not in (result.safe_summary_fa or "")


def test_tracking_reply_uses_clean_event_description() -> None:
    response = _success_response(
        events=[{"DateTime": "t", "ExtraInfo": _JSON_EXTRA, "Province": "تهران"}],
    )
    result = parse_iran_post_response(response, _TRACKING_24)
    reply = build_tracking_verification_chat_reply(result)
    assert _CLEAN_DESCRIPTION in reply
    assert _CARRIER_NAME not in reply
    assert "نامه رسان" not in reply
