"""Simplified operator-assisted work package UI (operational sections + debug expander)."""

from __future__ import annotations

from typing import Any

from app.agentic_sandbox.agentic_graph import NODE_ORDER
from app.evals.conceptual_intent_fa import fallback_conceptual_intent_fa
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    render_agentic_preview_markdown_or_lines,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import DEFAULT_CONSOLE_LANG, assisted_checklist_for_lang, is_fa, t

_MAIN_SECTION_KEYS = frozenset(
    {
        "vendor_summary",
        "suggested_action",
        "information_status",
        "extracted_entities",
        "internal_draft",
        "safety_status",
    },
)

_DEBUG_MARKERS = (
    "graph_status",
    "node_statuses",
    "knowledge_hint_document_types",
    "entity_extraction_source_char_count",
    "display_preview_char_count",
    "Graduation gate",
    "operator_checklist",
)


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    return str(value)


def _friendly_intent_label(graph: AgenticSandboxPreviewResult) -> str:
    if graph.conceptual_intent_fa:
        return graph.conceptual_intent_fa
    if graph.detected_intent:
        return fallback_conceptual_intent_fa(
            graph.detected_intent,
            source_text=None,
        )
    return "—"


def _first_turn_summary(ticket: OperatorTicket, *, max_chars: int = 280) -> str:
    text = (ticket.original_vendor_issue_preview or "").strip()
    if not text:
        return "—"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def build_assisted_work_package_main_sections(
    package: AgenticAssistedPackage,
    ticket: OperatorTicket,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> dict[str, str]:
    """Operator-facing section bodies (no graph debug metadata)."""
    graph = package.graph
    entity_lines: list[str] = []
    if graph.extracted_order_ids:
        entity_lines.append(f"{t('assisted_orders', lang)}: {graph.extracted_order_ids}")
    if graph.extracted_product_ids:
        entity_lines.append(f"{t('assisted_products', lang)}: {graph.extracted_product_ids}")
    if graph.extracted_tracking_code:
        entity_lines.append(
            f"{t('assisted_tracking', lang)}: {graph.extracted_tracking_code}",
        )
    if graph.extracted_iban_masked:
        entity_lines.append(f"{t('assisted_iban', lang)}: {graph.extracted_iban_masked}")
    if not entity_lines:
        entity_lines.append(t("assisted_no_entities", lang))

    actionable_label = t("assisted_actionable_yes", lang)
    if graph.actionability_actionable is False:
        actionable_label = t("assisted_actionable_no", lang)
    elif graph.actionability_actionable is None:
        actionable_label = "—"

    missing = graph.missing_required_entities or t("assisted_none_missing", lang)
    validation = graph.actionability_validation_reason or "—"

    safety_lines = [
        f"{t('assisted_human_review_required', lang)}: {_display(graph.human_review_required)}",
        f"{t('assisted_execution_disabled', lang)}: {_display(graph.execution_allowed is False)}",
        f"{t('assisted_customer_send_disabled', lang)}: "
        f"{_display(graph.customer_send_allowed is False)}",
        f"{t('safety_status', lang)}: {graph.safety_status or '—'}",
    ]

    return {
        "vendor_summary": (
            f"{_first_turn_summary(ticket)}\n\n"
            f"{t('detected_intent', lang)}: {_friendly_intent_label(graph)}"
        ),
        "suggested_action": (
            f"{t('suggested_action', lang)}: {graph.suggested_action or '—'}\n"
            f"{t('assisted_action_reason', lang)}: {graph.suggested_action_reason or '—'}"
        ),
        "information_status": (
            f"{t('actionability', lang)}: {actionable_label}\n"
            f"{t('assisted_missing_identifiers', lang)}: {missing}\n"
            f"{t('assisted_validation_reason', lang)}: {validation}"
        ),
        "extracted_entities": "\n".join(entity_lines),
        "internal_draft": graph.draft_reply or t("assisted_draft_unavailable", lang),
        "safety_status": "\n".join(safety_lines),
    }


def build_assisted_work_package_debug_lines(
    package: AgenticAssistedPackage,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> list[str]:
    """Technical graph metadata for collapsed debug expander."""
    graph = package.graph
    lines = [
        t("operator_checklist_heading", lang),
        *[f"- {item}" for item in assisted_checklist_for_lang(lang)],
        "",
        (f"- **Graduation gate:** {'passed' if package.graduation_gate_passed else 'not passed'}"),
        f"- **graduation_overall_status:** {package.graduation_overall_status or '—'}",
        "",
        t("structured_assistance_heading", lang),
    ]
    lines.extend(render_agentic_preview_markdown_or_lines(graph, lang=lang))
    lines.append("")
    lines.append("**Nodes (raw)**")
    for node in NODE_ORDER:
        status = graph.node_statuses.get(node, "pending")
        lines.append(f"- `{node}`: {status}")
    if graph.errors:
        lines.append("")
        lines.append("**Errors**")
        for error in graph.errors:
            lines.append(f"- {error[:200]}")
    return lines


def main_section_keys() -> frozenset[str]:
    return _MAIN_SECTION_KEYS


def debug_section_markers() -> tuple[str, ...]:
    return _DEBUG_MARKERS


def render_operator_assisted_work_package(
    streamlit: Any,
    package: AgenticAssistedPackage,
    ticket: OperatorTicket,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> None:
    """Render simplified assisted package in Streamlit."""
    sections = build_assisted_work_package_main_sections(package, ticket, lang=lang)
    graph = package.graph

    streamlit.markdown(f"##### {t('assisted_section_vendor_summary', lang)}")
    streamlit.markdown(sections["vendor_summary"])

    streamlit.markdown(f"##### {t('assisted_section_suggested_action', lang)}")
    streamlit.markdown(sections["suggested_action"])

    streamlit.markdown(f"##### {t('assisted_section_information_status', lang)}")
    streamlit.markdown(sections["information_status"])

    streamlit.markdown(f"##### {t('assisted_section_extracted_entities', lang)}")
    streamlit.markdown(sections["extracted_entities"])

    streamlit.markdown(f"##### {t('assisted_section_internal_draft', lang)}")
    streamlit.caption(t("internal_draft_caption", lang))
    source_key = None
    provider = (graph.draft_provider or "").strip().lower()
    if provider == "openai":
        source_key = "draft_source_openai"
    elif graph.draft_is_mock or provider in {"", "mock", "mock_fallback"}:
        source_key = "draft_source_mock_template"
    if source_key:
        streamlit.caption(t(source_key, lang))
    draft_text = graph.draft_reply or ""
    if is_fa(lang):
        streamlit.text_area(
            label=t("assisted_draft_review_box", lang),
            value=draft_text,
            height=140,
            disabled=True,
            key=f"assisted_draft_box_{ticket.room_id}",
        )
    else:
        streamlit.text_area(
            label=t("assisted_draft_review_box", lang),
            value=draft_text,
            height=140,
            disabled=True,
            key=f"assisted_draft_box_{ticket.room_id}",
        )
    meta = f"{t('draft_char_count', lang)}: {graph.draft_char_count}"
    if graph.draft_style:
        meta += f" · {t('draft_style', lang)}: {graph.draft_style}"
    streamlit.caption(meta)

    streamlit.markdown(f"##### {t('assisted_section_safety', lang)}")
    streamlit.markdown(sections["safety_status"])

    with streamlit.expander(t("assisted_debug_expander", lang), expanded=False):
        streamlit.markdown("\n".join(build_assisted_work_package_debug_lines(package, lang=lang)))
