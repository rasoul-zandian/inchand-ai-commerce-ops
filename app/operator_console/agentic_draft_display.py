"""Safe internal draft display for agentic sandbox / assisted mode (console only)."""

from __future__ import annotations

import html

from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.i18n import is_fa, t


def _draft_source_caption_key(result: AgenticSandboxPreviewResult) -> str | None:
    provider = (result.draft_provider or "").strip().lower()
    if provider == "openai":
        return "draft_source_openai"
    if result.draft_is_mock or provider in {"", "mock", "mock_fallback"}:
        return "draft_source_mock_template"
    return None


def render_agentic_internal_draft_html(
    result: AgenticSandboxPreviewResult,
    lang: str,
) -> str:
    """Render validated draft text for operator review; empty if no safe draft."""
    if not result.draft_reply:
        return ""

    title = t("internal_draft_suggestion", lang)
    caption = t("internal_draft_caption", lang)
    escaped_draft = html.escape(result.draft_reply.strip(), quote=False)
    source_note = ""
    source_key = _draft_source_caption_key(result)
    if source_key:
        source_note = (
            f'<div dir="ltr" lang="en" style="font-size:0.8rem;color:#666;'
            f'margin-bottom:0.35rem;">'
            f"{html.escape(t(source_key, lang), quote=False)}</div>"
        )

    meta_parts: list[str] = []
    meta_parts.append(f"{t('draft_char_count', lang)}: {result.draft_char_count}")
    if result.draft_style:
        style_val = html.escape(result.draft_style, quote=False)
        meta_parts.append(f"{t('draft_style', lang)}: {style_val}")
    if result.safety_status:
        meta_parts.append(
            f"{t('safety_status', lang)}: {html.escape(result.safety_status, quote=False)}",
        )
    meta_line = " · ".join(meta_parts)
    meta_html = (
        f'<div dir="ltr" lang="en" style="font-size:0.85rem;margin-bottom:0.5rem;">'
        f"{meta_line}</div>"
    )

    if is_fa(lang):
        body = (
            f'<div dir="rtl" style="text-align:right;white-space:pre-wrap;'
            f"line-height:1.6;padding:0.75rem;background:rgba(232,244,253,0.95);"
            f'border-radius:0.5rem;border-right:4px solid #1c83e1;">{escaped_draft}</div>'
        )
        header = (
            f'<div dir="rtl" style="font-weight:600;margin-bottom:0.25rem;">'
            f"{html.escape(title, quote=False)}</div>"
        )
        cap = (
            f'<div dir="rtl" style="font-size:0.85rem;color:#444;margin-bottom:0.5rem;">'
            f"{html.escape(caption, quote=False)}</div>"
        )
    else:
        body = (
            f'<div dir="ltr" style="text-align:left;white-space:pre-wrap;'
            f"line-height:1.6;padding:0.75rem;background:rgba(232,244,253,0.95);"
            f'border-radius:0.5rem;border-left:4px solid #1c83e1;">{escaped_draft}</div>'
        )
        escaped_title = html.escape(title, quote=False)
        header = f'<div style="font-weight:600;margin-bottom:0.25rem;">{escaped_title}</div>'
        cap = (
            f'<div style="font-size:0.85rem;color:#444;margin-bottom:0.5rem;">'
            f"{html.escape(caption, quote=False)}</div>"
        )

    return (
        f'<div class="operator-agentic-draft" style="margin:0.75rem 0;">'
        f"{header}{cap}{source_note}{meta_html}{body}</div>"
    )
