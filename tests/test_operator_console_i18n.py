"""Tests for operator console FA/EN i18n and RTL layout helpers."""

from __future__ import annotations

from app.operator_console.agentic_draft_display import render_agentic_internal_draft_html
from app.operator_console.agentic_sandbox_preview import sanitize_agentic_preview_result
from app.operator_console.i18n import (
    CONSOLE_LANG_SESSION_KEY,
    LANG_EN,
    LANG_FA,
    apply_console_direction_css,
    get_console_language,
    set_console_language,
    t,
)


def _final_state() -> dict[str, object]:
    return {
        "room_id": "7743",
        "detected_intent": "settlement_status_inquiry",
        "suggested_action": "billing_review",
        "actionability": {"actionability_actionable": True},
        "extracted_entities": {"order_ids": [], "product_ids": []},
        "draft_reply": "پاسخ کوتاه برای بررسی",
        "safety_status": "passed",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "errors": [],
        "node_results": [],
    }


def test_fa_mode_css_includes_rtl() -> None:
    css = apply_console_direction_css(LANG_FA)
    assert "direction: rtl" in css
    assert "text-align: right" in css
    assert "right: 0" in css


def test_en_mode_does_not_force_rtl() -> None:
    assert apply_console_direction_css(LANG_EN) == ""


def test_translation_fallback_for_missing_key() -> None:
    assert t("nonexistent.translation.key", LANG_EN) == "nonexistent.translation.key"


def test_default_language_is_fa() -> None:
    assert get_console_language({}) == LANG_FA


def test_session_language_roundtrip() -> None:
    session: dict[str, str] = {}
    set_console_language(session, LANG_EN)
    assert session[CONSOLE_LANG_SESSION_KEY] == LANG_EN
    assert get_console_language(session) == LANG_EN


def test_draft_display_block_includes_rtl_in_fa_mode() -> None:
    preview = sanitize_agentic_preview_result(_final_state(), knowledge_hints_enabled=True)
    assert preview.draft_reply is not None
    html_block = render_agentic_internal_draft_html(preview, LANG_FA)
    assert 'dir="rtl"' in html_block
    assert "پاسخ کوتاه" in html_block


def test_draft_display_ltr_in_en_mode() -> None:
    preview = sanitize_agentic_preview_result(_final_state(), knowledge_hints_enabled=True)
    html_block = render_agentic_internal_draft_html(preview, LANG_EN)
    assert 'dir="ltr"' in html_block
