"""Tests for exploratory Persian conceptual_intent_fa draft labels."""

from __future__ import annotations

import json

import pytest
from app.config import AppSettings
from app.evals.conceptual_intent_fa import (
    assert_conceptual_intent_safe,
    fallback_conceptual_intent_fa,
    normalize_conceptual_intent_label,
    parse_draft_generation_content,
    resolve_conceptual_intent_fa,
)
from app.evals.offline_draft_generation import process_benchmark_case
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.draft_preview import build_draft_preview_record


def test_parses_json_model_output() -> None:
    content = json.dumps(
        {
            "conceptual_intent_fa": "پیگیری تسویه حساب",
            "draft_reply": "سلام — واحد مالی در حال بررسی است.",
        },
        ensure_ascii=False,
    )
    result = parse_draft_generation_content(
        content,
        detected_intent="settlement_status_inquiry",
    )
    assert result.conceptual_intent_fa == "پیگیری تسویه حساب"
    assert "سلام" in result.draft_reply


def test_rejects_conceptual_intent_longer_than_four_words() -> None:
    with pytest.raises(ValueError, match="max words"):
        assert_conceptual_intent_safe("کلمه یک دو سه چهار پنج")


def test_rejects_unsafe_conceptual_intent_iban() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_conceptual_intent_safe("کارت 6037991234567890")


def test_fallback_when_plain_text_draft_only() -> None:
    result = parse_draft_generation_content(
        "سلام وقت بخیر. درخواست شما بررسی می‌شود.",
        detected_intent="product_approval_review",
    )
    assert result.conceptual_intent_fa == "درخواست تایید کالا"
    assert "سلام" in result.draft_reply


def test_fallback_when_conceptual_intent_invalid() -> None:
    resolved = resolve_conceptual_intent_fa(
        "this is not persian readable enough",
        detected_intent="complaint_escalation",
    )
    assert resolved == "پیگیری شکایت"


def test_normalize_conceptual_intent_label() -> None:
    assert normalize_conceptual_intent_label("  درخواست   ویرایش کالا  ") == "درخواست ویرایش کالا"


def test_old_draft_row_loads_without_conceptual_intent() -> None:
    row = {
        "room_id": "ROOM_OLD",
        "draft_reply": "سلام — پیش‌نویس قدیمی.",
        "detected_intent": "general_vendor_support",
        "draft_generated": True,
    }
    record = build_draft_preview_record(row)
    assert record is not None
    assert record.conceptual_intent_fa is None


def test_process_benchmark_case_includes_conceptual_intent() -> None:
    case = {
        "case_id": "ROOM_CI__first_vendor_turn",
        "room_id": "ROOM_CI",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": "تسویه من واریز نشده",
            "latest_vendor_message": "لطفاً وضعیت را بگویید",
            "recent_context_preview": "vendor: تسویه",
        },
        "gold_reference_reply": "gold must not leak",
    }

    def _mock_generate(_messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(
                {
                    "conceptual_intent_fa": "پیگیری تسویه حساب",
                    "draft_reply": "سلام — درخواست تسویه در صف بررسی است.",
                },
                ensure_ascii=False,
            ),
            provider=provider,
            model=model,
            metadata={},
        )

    row = process_benchmark_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
        provider="mock",
        model="mock",
        generate_fn=_mock_generate,
    )
    assert row["draft_generated"] is True
    assert row["conceptual_intent_fa"] == "پیگیری تسویه حساب"
    assert row["detected_intent"] == "settlement_status_inquiry"


def test_fallback_mapping_covers_general_vendor_support() -> None:
    assert fallback_conceptual_intent_fa("general_vendor_support") == "پشتیبانی عمومی فروشنده"
