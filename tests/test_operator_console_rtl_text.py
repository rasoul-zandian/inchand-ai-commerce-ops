"""Tests for operator console RTL / recent-context formatting (UI helpers only)."""

from __future__ import annotations

import html

from app.operator_console.rtl_text import format_context_lines, render_rtl_text_block


def test_format_context_lines_splits_pipe_joined_segments() -> None:
    raw = "support: در حال بررسی هستیم | vendor: لطفاً سریع‌تر پیگیری کنید"
    out = format_context_lines(raw)
    assert "\n" in out
    assert " | " not in out
    assert "support:" in out
    assert "vendor:" in out


def test_format_context_lines_preserves_speaker_labels() -> None:
    raw = "finance: IR tax form | vendor: Waiting"
    out = format_context_lines(raw)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("finance:")
    assert lines[1].startswith("vendor:")


def test_format_context_lines_single_segment_unchanged() -> None:
    text = "vendor: only one line here"
    assert format_context_lines(text) == text


def test_format_context_lines_mixed_persian_english_numbers_unchanged() -> None:
    text = "vendor: سلام Hello 123 [PHONE_NUMBER]"
    assert format_context_lines(text) == text


def test_render_rtl_text_block_escapes_html_no_raw_injection() -> None:
    malicious = "<script>alert(1)</script>"
    block = render_rtl_text_block("Section", malicious)
    assert "<script>" not in block
    assert html.escape(malicious, quote=False) in block


def test_render_rtl_text_block_does_not_emit_messages_array_token() -> None:
    """Helper only echoes escaped payload text; no transcript keys are injected."""
    block = render_rtl_text_block("Body", "vendor: ok")
    assert '"messages"' not in block
    assert "messages[" not in block


def test_render_rtl_text_block_empty_body_returns_empty() -> None:
    assert render_rtl_text_block("L", "   ") == ""
