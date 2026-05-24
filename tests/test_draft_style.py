"""Tests for operational_short draft style validation."""

from __future__ import annotations

from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import prompt_text_from_messages
from app.evals.draft_style import (
    DRAFT_STYLE_OPERATIONAL_SHORT,
    apply_operational_short_style_checks,
    build_draft_style_instruction,
    count_persian_sentences,
    validate_operational_short_draft,
)
from app.evals.first_turn_draft_context import build_first_turn_draft_context_from_case
from app.evals.offline_draft_generation import build_offline_draft_messages


def test_short_operational_draft_passes_validation() -> None:
    text = "برای بررسی به تیم مربوطه ارجاع شد."
    result = validate_operational_short_draft(text)
    assert result.draft_style_ok is True
    assert result.draft_char_count == len(text)
    assert result.draft_sentence_count >= 1


def test_long_draft_fails_validation() -> None:
    text = "جمله اول. " + "ا" * 200 + " جمله دوم."
    result = validate_operational_short_draft(text)
    assert result.draft_style_ok is False
    assert result.draft_style_warnings


def test_banned_phrase_detected() -> None:
    text = "درخواست شما با موفقیت ثبت شد."
    result = validate_operational_short_draft(text)
    assert result.draft_style_ok is False
    assert any("banned phrase" in w for w in result.draft_style_warnings)


def test_count_persian_sentences() -> None:
    assert count_persian_sentences("سلام. خداحافظ") == 2
    assert count_persian_sentences("یک جمله") == 1


def test_prompt_includes_style_instruction() -> None:
    case = {
        "case_id": "ROOM_ST__first_vendor_turn",
        "room_id": "ROOM_ST",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": "لطفاً وضعیت سفارش 1234567 را بررسی کنید",
            "latest_vendor_message": "پیام بعدی",
        },
    }
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    messages = build_offline_draft_messages(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    prompt = prompt_text_from_messages(messages)
    assert "operational_short" in prompt
    assert "۱ تا ۲ جمله" in prompt


def test_build_draft_style_instruction_operational_short() -> None:
    block = build_draft_style_instruction(DRAFT_STYLE_OPERATIONAL_SHORT)
    assert "کوتاه" in block
    assert "تیم مربوطه" in block


def test_apply_style_checks_from_settings() -> None:
    settings = AppSettings(draft_style="operational_short", draft_hard_max_chars=300)
    result = apply_operational_short_style_checks(
        "برای بررسی به تیم مربوطه ارجاع شد.",
        settings,
    )
    assert result.draft_style == DRAFT_STYLE_OPERATIONAL_SHORT
    assert result.draft_style_ok is True
