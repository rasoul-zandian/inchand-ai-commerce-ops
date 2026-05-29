"""Extraction, payload field, and diagnostics tests for Iran Post tracking."""

from __future__ import annotations

import json

from app.config import AppSettings
from app.operator_console.manual_sandbox_auto_tracking import (
    try_manual_sandbox_auto_tracking_verify,
)
from app.tools.tracking.iran_post_tracking import (
    build_iran_post_request_payload,
    extract_iran_post_tracking_candidates,
    infer_plausible_iran_post_tracking_code_from_text,
    normalize_tracking_code,
    parse_iran_post_response,
    resolve_tracking_code_from_text,
    select_iran_post_tracking_candidate,
    verify_iran_post_tracking_code,
)

_TRACKING_24 = "051800506400081160839102"
_PERSIAN_24 = "۰۵۱۸۰۰۵۰۶۴۰۰۰۸۱۱۶۰۸۳۹۱۰۲"
_ARABIC_24 = "٠٥١٨٠٠٥٠٦٤٠٠٠٨١١٦٠٨٣٩١٠٢"
_ORDER_7 = "7367917"
_PHONE = "09121234567"


def test_persian_digits_normalize() -> None:
    assert normalize_tracking_code(_PERSIAN_24) == _TRACKING_24


def test_arabic_digits_normalize() -> None:
    assert normalize_tracking_code(_ARABIC_24) == _TRACKING_24


def test_spaces_and_dashes_removed() -> None:
    raw = "0518 0050-6400-081160839102"
    assert normalize_tracking_code(raw) == _TRACKING_24


def test_7_digit_order_id_rejected_in_candidates() -> None:
    text = f"شماره سفارش {_ORDER_7} است."
    candidates = extract_iran_post_tracking_candidates(text)
    assert all(not candidate.plausible for candidate in candidates)
    assert infer_plausible_iran_post_tracking_code_from_text(text) is None


def test_24_digit_tracking_selected() -> None:
    selected, diagnostics = resolve_tracking_code_from_text(_TRACKING_24)
    assert selected == _TRACKING_24
    assert diagnostics.selected_candidate_reason in {
        "exact_24_digit",
        "exact_24_near_tracking_keyword",
        "plausible_whole_message",
    }


def test_keyword_proximity_preferred() -> None:
    text = f"سفارش {_ORDER_7} است. کد رهگیری: {_TRACKING_24} و شماره تماس {_PHONE}"
    selected, diagnostics = resolve_tracking_code_from_text(text)
    assert selected == _TRACKING_24
    assert diagnostics.selected_candidate_reason in {
        "exact_24_near_tracking_keyword",
        "exact_24_digit",
        "keyword_proximity",
    }


def test_phone_number_not_selected() -> None:
    text = f"لطفاً تماس بگیرید {_PHONE}"
    assert infer_plausible_iran_post_tracking_code_from_text(text) is None


def test_multiple_candidates_prefer_exact_24() -> None:
    shorter_plausible = "1" * 20
    text = f"کد قدیمی {shorter_plausible} و کد رهگیری {_TRACKING_24}"
    selected, diagnostics = resolve_tracking_code_from_text(text)
    assert selected == _TRACKING_24
    assert diagnostics.selected_tracking_code == _TRACKING_24


def test_payload_package_number_default() -> None:
    payload, params = build_iran_post_request_payload(_TRACKING_24, "tok")
    assert payload["Parameters"]["PackageNumber"] == _TRACKING_24
    assert payload["Parameters"]["TraceNumber"] == ""
    assert params["PackageNumber"] == _TRACKING_24
    assert params["TraceNumber"] == ""


def test_payload_trace_number_for_diagnostics() -> None:
    _, params = build_iran_post_request_payload(
        _TRACKING_24,
        "tok",
        code_field="TraceNumber",
    )
    assert params["TraceNumber"] == _TRACKING_24
    assert params["PackageNumber"] == ""


def test_payload_both_for_diagnostics() -> None:
    _, params = build_iran_post_request_payload(
        _TRACKING_24,
        "tok",
        code_field="both",
    )
    assert params["PackageNumber"] == _TRACKING_24
    assert params["TraceNumber"] == _TRACKING_24


def test_manual_sandbox_uses_candidate_extractor_not_order_id() -> None:
    session: dict[str, object] = {}
    settings = AppSettings(
        manual_sandbox_auto_tracking_verify_enabled=True,
        iran_post_tracking_enabled=True,
        iran_post_tracking_token="tok",
    )
    text = f"سفارش {_ORDER_7} — کد رهگیری {_TRACKING_24}"

    def _mock_verify(code: str):
        return parse_iran_post_response(
            {
                "Status": {"Code": "0", "Description": "OK"},
                "Parameters": {"PostPackageStatusDetail": []},
            },
            code,
        )

    outcome = try_manual_sandbox_auto_tracking_verify(
        text,
        seller_message_id="m1",
        session_state=session,
        settings=settings,
        verify_fn=_mock_verify,
    )
    assert outcome.tracking_code == _TRACKING_24
    assert outcome.extraction_diagnostics is not None
    assert outcome.extraction_diagnostics.selected_tracking_code == _TRACKING_24


def test_debug_diagnostics_contain_selected_code_no_token() -> None:
    settings = AppSettings(
        iran_post_tracking_enabled=True,
        iran_post_tracking_token="secret-token",
    )

    def _mock_post(_url: str, payload: object, _timeout: float) -> dict:
        assert isinstance(payload, dict)
        assert payload["Identity"]["Token"] == "secret-token"
        assert "secret-token" not in json.dumps(payload.get("Parameters", {}))
        return {
            "Status": {"Code": "0", "Description": "OK"},
            "Parameters": {"PostPackageStatusDetail": []},
        }

    text = f"کد رهگیری: {_PERSIAN_24}"
    result = verify_iran_post_tracking_code(
        text,
        settings=settings,
        http_client=_mock_post,
    )
    assert result.extraction_diagnostics is not None
    diag = result.extraction_diagnostics.to_safe_dict()
    assert diag["selected_tracking_code"] == _TRACKING_24
    assert diag["payload_package_number"] == _TRACKING_24
    assert diag["payload_trace_number"] in (None, "")
    blob = json.dumps(diag)
    assert "secret-token" not in blob
    assert "Token" not in blob


def test_select_prefers_plausible_over_rejected() -> None:
    candidates = extract_iran_post_tracking_candidates(
        f"order {_ORDER_7} tracking {_TRACKING_24}",
    )
    selected, reason = select_iran_post_tracking_candidate(
        candidates,
        f"order {_ORDER_7} tracking {_TRACKING_24}",
    )
    assert selected is not None
    assert selected.normalized_code == _TRACKING_24
    assert reason
