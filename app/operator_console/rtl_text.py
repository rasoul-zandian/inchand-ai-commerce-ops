"""RTL-aware formatting for operator console ticket previews (UI only; no payload changes)."""

from __future__ import annotations

import html

from app.operator_console.display_text import clean_redaction_placeholders_for_display

# Joiner used by `app/live_feed/open_ticket_snapshot.extract_recent_context`
_CONTEXT_SEGMENT_JOINER = " | "

_RTL_BODY_BASE = (
    "text-align:right;"
    "unicode-bidi:isolate;"
    "white-space:pre-wrap;"
    "line-height:1.6;"
    "padding:0.75rem;"
    "background:rgba(232,244,253,0.95);"
    "border-radius:0.5rem;"
    "border-left:4px solid #1c83e1;"
)


def format_context_lines(text: str) -> str:
    """Normalize recent-context preview to one chat-style line per message.

    Pipe-joined segments from the snapshot builder become separate lines;
    other text is returned stripped unchanged.
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    if _CONTEXT_SEGMENT_JOINER in cleaned:
        parts = [p.strip() for p in cleaned.split(_CONTEXT_SEGMENT_JOINER)]
        return "\n".join(p for p in parts if p)
    return cleaned


def render_rtl_text_block(label: str, text: str, *, compact: bool = False) -> str:
    """Return a small HTML fragment for Streamlit (``unsafe_allow_html=True``).

    Renders body RTL with mixed Persian/Latin/numbers; optional English section
    label stays LTR. Content is HTML-escaped (no raw HTML injection).
    """
    body = clean_redaction_placeholders_for_display(text.strip())
    if not body:
        return ""
    escaped_body = html.escape(body, quote=False)
    font = "font-size:0.85rem;" if compact else ""
    rtl_style = _RTL_BODY_BASE + font
    rtl_inner = f'<div dir="rtl" style="{rtl_style}">{escaped_body}</div>'

    label_stripped = label.strip()
    if not label_stripped:
        return f'<div class="operator-rtl-root">{rtl_inner}</div>'

    escaped_label = html.escape(label_stripped, quote=False)
    header = (
        f'<div dir="ltr" lang="en" style="font-size:0.875rem;font-weight:600;'
        f'margin-bottom:0.35rem;">{escaped_label}</div>'
    )
    return (
        f'<div class="operator-rtl-root" style="margin-bottom:0.75rem;">{header}{rtl_inner}</div>'
    )
