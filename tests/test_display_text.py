"""Tests for operator-console display-only redaction placeholder cleanup."""

from __future__ import annotations

from app.operator_console.display_text import clean_redaction_placeholders_for_display
from app.operator_console.rtl_text import render_rtl_text_block


def test_placeholder_replacement() -> None:
    text = "تماس [PHONE_NUMBER] و شبا [IBAN] و [EMAIL]"
    out = clean_redaction_placeholders_for_display(text)
    assert "[PHONE_NUMBER]" not in out
    assert "[IBAN]" not in out
    assert "[EMAIL]" not in out
    assert "«شماره تماس حذف شده»" in out
    assert "«شماره شبا حذف شده»" in out
    assert "«ایمیل حذف شده»" in out


def test_repeated_placeholders_and_extra_spaces() -> None:
    text = "[PHONE_NUMBER]   [PHONE_NUMBER]  [CARD_NUMBER]"
    out = clean_redaction_placeholders_for_display(text)
    assert out.count("«شماره تماس حذف شده»") == 2
    assert "«شماره کارت حذف شده»" in out
    assert "  " not in out


def test_normal_persian_text_unchanged() -> None:
    text = "سلام وقت بخیر — لطفاً سفارش ۱۲۳۴۵۶۷ را پیگیری کنید."
    assert clean_redaction_placeholders_for_display(text) == text


def test_render_rtl_applies_display_cleanup() -> None:
    block = render_rtl_text_block("Issue", "vendor: [PHONE_NUMBER]")
    assert "[PHONE_NUMBER]" not in block
    assert "شماره تماس حذف شده" in block
