"""Tests for operational (action) phrasing of conceptual_intent_fa."""

from __future__ import annotations

import pytest
from app.evals.conceptual_intent_fa import (
    extract_operational_request_phrase,
    is_generic_conceptual_label,
    resolve_conceptual_intent_fa,
)
from app.evals.offline_draft_generation import build_offline_draft_messages
from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent


@pytest.mark.parametrize(
    ("seller_text", "expected"),
    [
        (
            "لطفا وضعیت این سفارش رو هم به تحویل شده تغییر بدید",
            "ثبت تحویل سفارش",
        ),
        (
            "کالای من تایید نشده",
            "درخواست تایید کالا",
        ),
        (
            "مرجوعی این سفارش را بررسی کنید",
            "پیگیری مرجوعی سفارش",
        ),
        (
            "لطفا اطلاعات کالا را ویرایش کنید",
            "درخواست ویرایش کالا",
        ),
        (
            "چرا تسویه انجام نشده؟",
            "پیگیری تسویه حساب",
        ),
    ],
)
def test_extract_operational_request_phrase(seller_text: str, expected: str) -> None:
    assert extract_operational_request_phrase(seller_text) == expected


def test_rejects_generic_label_when_operational_hint_exists() -> None:
    source = "لطفا وضعیت این سفارش رو هم به تحویل شده تغییر بدید"
    resolved = resolve_conceptual_intent_fa(
        "استعلام وضعیت سفارش",
        detected_intent="order_status_review",
        source_text=source,
    )
    assert resolved == "ثبت تحویل سفارش"


def test_rejects_topic_style_labels() -> None:
    assert is_generic_conceptual_label("بررسی درخواست فروشنده")
    assert is_generic_conceptual_label("سوال درباره کالا")
    assert is_generic_conceptual_label("استعلام وضعیت سفارش")
    assert not is_generic_conceptual_label("ثبت تحویل سفارش")


def test_prompt_includes_operational_instruction() -> None:
    seller_text = "لطفا وضعیت این سفارش رو هم به تحویل شده تغییر بدید"
    case = {
        "ticket_label": "support",
        "route_label": "order_review",
        "snapshot_before_reply": {"original_vendor_issue_preview": seller_text},
    }
    intent = detect_vendor_ticket_intent(seller_text)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="general_support",
        policy_hints=[],
    )
    combined = "\n".join(m.content for m in messages)
    assert "اقدام یا درخواستی" in combined
    assert "ثبت تحویل سفارش" in combined
    assert "بررسی درخواست فروشنده" in combined
    assert "پرهیز کن" in combined


def test_fallback_uses_operational_phrase_over_generic_mapping() -> None:
    source = "چرا تسویه انجام نشده؟"
    resolved = resolve_conceptual_intent_fa(
        None,
        detected_intent="general_vendor_support",
        source_text=source,
    )
    assert resolved == "پیگیری تسویه حساب"
