"""Session-only reflection before/after draft comparison for operator console (eval/debug)."""

from __future__ import annotations

from typing import Any

from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.i18n import DEFAULT_CONSOLE_LANG, is_fa, t
from app.workflows.operational_information_sufficiency import _SENTENCE_SPLIT_RE

_FORBIDDEN_DIFF_MARKERS = (
    "chain of thought",
    "chain-of-thought",
    "hidden reasoning",
    "reviewer thoughts",
    "raw_prompt",
    '"snippet":',
)


def reflection_comparison_available(graph: AgenticSandboxPreviewResult) -> bool:
    """True when assisted package has session comparison drafts to display."""
    if graph.reflection_comparison_available:
        return True
    return bool((graph.pre_reflection_draft or graph.draft_reply or "").strip())


def reflection_draft_diff_lines(before: str, after: str) -> list[str]:
    """Lightweight sentence-level diff summary (safe labels only)."""
    before_text = before.strip()
    after_text = after.strip()
    if not before_text and not after_text:
        return []
    if before_text == after_text:
        return []

    before_parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(before_text) if part.strip()]
    after_parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(after_text) if part.strip()]
    before_set = set(before_parts)
    after_set = set(after_parts)
    removed = [part for part in before_parts if part not in after_set]
    added = [part for part in after_parts if part not in before_set]
    lines: list[str] = []
    for part in removed:
        lines.append(f"- removed: {part}")
    for part in added:
        lines.append(f"- added: {part}")
    return lines


def build_reflection_comparison_metadata_lines(
    graph: AgenticSandboxPreviewResult,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> list[str]:
    """Safe reflection metadata lines (no hidden reasoning)."""
    issue_types = ", ".join(graph.reflection_issue_types) if graph.reflection_issue_types else "—"
    provider = graph.reflection_provider or "—"
    return [
        f"{t('reflection_enabled_label', lang)}: {_bool_label(graph.reflection_enabled, lang)}",
        f"{t('reflection_provider_label', lang)}: {provider}",
        f"{t('reflection_reviewed_label', lang)}: {_bool_label(graph.reflection_reviewed, lang)}",
        f"{t('reflection_rewrite_label', lang)}: "
        f"{_bool_label(graph.reflection_rewrite_applied, lang)}",
        f"{t('reflection_issue_types_label', lang)}: {issue_types}",
        f"{t('reflection_issue_count_label', lang)}: {graph.reflection_issue_count}",
    ]


def render_reflection_comparison_section(
    streamlit: Any,
    graph: AgenticSandboxPreviewResult,
    ticket_room_id: str,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> None:
    """Render before/after reflection drafts in main assisted mode (always when package exists)."""
    before = (graph.pre_reflection_draft or graph.draft_reply or "").strip()
    after = (graph.final_reflected_draft or graph.draft_reply or "").strip()
    if not before and not after:
        streamlit.info(t("reflection_comparison_unavailable", lang))
        return

    with streamlit.expander(t("reflection_comparison_expander", lang), expanded=False):
        streamlit.caption(t("reflection_comparison_caption", lang))
        streamlit.markdown(f"**{t('reflection_metadata_heading', lang)}**")
        for line in build_reflection_comparison_metadata_lines(graph, lang=lang):
            streamlit.markdown(line)

        if graph.reflection_enabled is False:
            streamlit.warning(t("reflection_disabled_warning", lang))

        streamlit.markdown(f"**{t('reflection_before_label', lang)}**")
        streamlit.text_area(
            label=t("reflection_before_label", lang),
            value=before,
            height=120,
            disabled=True,
            key=f"reflection_before_{ticket_room_id}",
            label_visibility="collapsed",
        )
        streamlit.markdown(f"**{t('reflection_after_label', lang)}**")
        streamlit.text_area(
            label=t("reflection_after_label", lang),
            value=after,
            height=120,
            disabled=True,
            key=f"reflection_after_{ticket_room_id}",
            label_visibility="collapsed",
        )

        if before == after and graph.reflection_reviewed:
            streamlit.info(t("reflection_no_change_caption", lang))

        raw_generated = (graph.raw_generated_draft or "").strip()
        if raw_generated and raw_generated != before:
            streamlit.caption(
                f"{t('reflection_raw_generated_label', lang)}: {raw_generated[:280]}"
                + ("…" if len(raw_generated) > 280 else ""),
            )

        diff_lines = reflection_draft_diff_lines(before, after)
        if diff_lines:
            streamlit.markdown(f"**{t('reflection_diff_heading', lang)}**")
            for line in diff_lines:
                streamlit.markdown(line)

        _assert_reflection_comparison_text_safe(before, after)


# Backward-compatible alias for tests/imports.
render_reflection_comparison_expander = render_reflection_comparison_section


def reflection_disabled_debug_line(
    graph: AgenticSandboxPreviewResult,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> str | None:
    """Technical-details warning when reflection is disabled."""
    if graph.reflection_enabled is False:
        return t("reflection_disabled_technical_warning", lang)
    return None


def _bool_label(value: bool | None, lang: str) -> str:
    if value is None:
        return "—"
    if is_fa(lang):
        return "بله" if value else "خیر"
    return "yes" if value else "no"


def _assert_reflection_comparison_text_safe(*texts: str) -> None:
    for text in texts:
        lowered = text.lower()
        for marker in _FORBIDDEN_DIFF_MARKERS:
            if marker in lowered:
                raise ValueError("reflection comparison UI must not display forbidden content")
