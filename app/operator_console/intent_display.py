"""Operator-console display helpers for operational intent taxonomy v1."""

from __future__ import annotations

from app.config import get_settings
from app.evals.draft_generation_mode import DraftGenerationMode, parse_draft_generation_mode
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    first_turn_extraction_text_from_ticket,
    resolve_first_turn_text_sources_from_ticket,
)
from app.operator_console.console_models import OperatorTicket
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
    mask_sensitive_entity,
)

_EMPTY_INTENT_MESSAGE = "No detected operational intent available."


def iban_display_value(
    *,
    full_iban: str | None,
    masked_iban: str | None = None,
    show_full: bool | None = None,
) -> str:
    """Operator-console Sheba/IBAN display (full for calibration, masked when configured)."""
    if show_full is None:
        show_full = get_settings().show_full_iban_in_operator_console
    if not full_iban and not masked_iban:
        return "—"
    if show_full and full_iban:
        return full_iban
    if masked_iban:
        return masked_iban
    if full_iban:
        return mask_sensitive_entity(full_iban)
    return "—"


_OPEN_SNAPSHOT_ENTITY_SOURCE = "open_snapshot_ai_assist"


def ticket_has_operational_intent_data(ticket: OperatorTicket) -> bool:
    """True when any intent or extracted entity field is present for display."""
    return bool(
        ticket.detected_intent
        or ticket.intent_confidence_band
        or ticket.intent_reasons_summary
        or ticket.intent_related_document_types
        or ticket.extracted_order_ids
        or ticket.extracted_order_id
        or ticket.extracted_tracking_code
        or ticket.extracted_iban
        or ticket.extracted_iban_masked
    )


def ticket_has_operational_entity_data(ticket: OperatorTicket) -> bool:
    """True when structured entity fields (order/product/tracking/warnings) are present."""
    return bool(
        ticket.extracted_order_ids
        or ticket.extracted_order_id
        or ticket.extracted_product_ids
        or ticket.extracted_tracking_code
        or ticket.entity_warnings_summary
        or ticket.extracted_iban_masked
    )


def format_operational_intent_lines(ticket: OperatorTicket) -> list[str]:
    """Markdown bullet lines for Streamlit; empty list means show fallback message only."""
    if not ticket_has_operational_intent_data(ticket):
        return []
    return [
        f"- **Intent:** {ticket.detected_intent or '—'}",
        f"- **Confidence:** {ticket.intent_confidence_band or '—'}",
        f"- **Reasons:** {ticket.intent_reasons_summary or '—'}",
        f"- **Related docs:** {ticket.intent_related_document_types or '—'}",
    ]


def entity_extraction_has_display_data(result: OperationalEntityExtractionResult) -> bool:
    """True when extraction result has any field worth showing in the console."""
    return bool(
        result.order_ids
        or result.product_ids
        or result.primary_tracking_code
        or result.entity_warnings_summary
        or result.primary_iban,
    )


def format_entity_extraction_lines(
    result: OperationalEntityExtractionResult,
    *,
    entity_source: str,
    source_char_count: int | None = None,
    display_preview_char_count: int | None = None,
) -> list[str]:
    """Markdown bullets for a single extraction result and its source label."""
    if not entity_extraction_has_display_data(result):
        return []
    order_ids = ",".join(result.order_ids) if result.order_ids else None
    product_ids = ",".join(result.product_ids) if result.product_ids else None
    carrier = result.primary_tracking_carrier.value if result.primary_tracking_carrier else "—"
    warnings = result.entity_warnings_summary or "—"
    iban_display = iban_display_value(
        full_iban=result.primary_iban,
        masked_iban=result.primary_iban_masked,
    )
    lines = [
        f"- **Entity source:** {entity_source}",
    ]
    if source_char_count is not None:
        lines.append(f"- **Source length:** {source_char_count} chars")
    if display_preview_char_count is not None:
        lines.append(f"- **Display preview length:** {display_preview_char_count} chars")
    lines.extend(
        [
            f"- **Order IDs:** {order_ids or '—'}",
            f"- **Product IDs:** {product_ids or '—'}",
            f"- **Tracking code:** {result.primary_tracking_code or '—'}",
            f"- **Sheba / IBAN:** {iban_display}",
            f"- **Carrier:** {carrier}",
            f"- **Warnings:** {warnings}",
        ],
    )
    return lines


def extract_first_turn_display_entities(
    ticket: OperatorTicket,
) -> OperationalEntityExtractionResult:
    """Entities for console display in first_turn_only mode (full first seller message when set)."""
    return extract_operational_entities(first_turn_extraction_text_from_ticket(ticket))


def format_first_turn_entity_lines(ticket: OperatorTicket) -> list[str]:
    """Main entity block for first-turn calibration — never uses OperatorTicket globals."""
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    lines = format_entity_extraction_lines(
        extract_first_turn_display_entities(ticket),
        entity_source=sources.entity_extraction_source,
        source_char_count=sources.entity_extraction_source_char_count,
        display_preview_char_count=sources.display_preview_char_count,
    )
    if lines:
        return lines
    label = sources.entity_extraction_source or ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    return [f"- **Entity source:** {label}"]


def format_open_snapshot_entity_lines(ticket: OperatorTicket) -> list[str]:
    """Debug entity block from AI assist / open snapshot fields on the ticket row."""
    if not ticket_has_operational_entity_data(ticket):
        return []
    order_ids = ticket.extracted_order_ids or ticket.extracted_order_id
    carrier = ticket.extracted_tracking_carrier or "—"
    warnings = ticket.entity_warnings_summary or "—"
    iban_display = iban_display_value(
        full_iban=ticket.extracted_iban,
        masked_iban=ticket.extracted_iban_masked,
    )
    return [
        f"- **Entity source:** {_OPEN_SNAPSHOT_ENTITY_SOURCE}",
        f"- **Order IDs:** {order_ids or '—'}",
        f"- **Product IDs:** {ticket.extracted_product_ids or '—'}",
        f"- **Tracking code:** {ticket.extracted_tracking_code or '—'}",
        f"- **Sheba / IBAN:** {iban_display}",
        f"- **Carrier:** {carrier}",
        f"- **Warnings:** {warnings}",
    ]


def format_operational_entity_lines(ticket: OperatorTicket) -> list[str]:
    """Markdown bullets for open-snapshot / live-thread entity display (ticket globals)."""
    return format_open_snapshot_entity_lines(ticket)


def use_first_turn_entity_display(*, draft_generation_mode: str | DraftGenerationMode) -> bool:
    """True when console should show first-turn entities as the primary entity section."""
    if isinstance(draft_generation_mode, DraftGenerationMode):
        mode = draft_generation_mode
    else:
        mode = parse_draft_generation_mode(draft_generation_mode)
    return mode == DraftGenerationMode.FIRST_TURN_ONLY


def first_turn_entity_section_title() -> str:
    return "Extracted entities (first-turn only)"


def open_snapshot_entity_section_title() -> str:
    return "Extracted entities (open snapshot / AI assist)"


def first_turn_entity_section_caption() -> str:
    return (
        "Rule-based IDs from the first seller message only (full internal source when "
        "available; truncated preview for display/prompts) — not verified against "
        "orders/products/carriers."
    )


def open_snapshot_entity_section_caption() -> str:
    return (
        "Rule-based IDs from open ticket snapshot and AI assist previews (may include "
        "latest seller message) — not verified against orders/products/carriers."
    )


def first_turn_entity_fallback_message() -> str:
    return "No first-turn entities extracted from the first seller message."


def operational_intent_fallback_message() -> str:
    return _EMPTY_INTENT_MESSAGE


def operational_entity_fallback_message() -> str:
    return "No extracted operational entities available."


def format_draft_entity_lines(
    *,
    draft_entity_source: str | None,
    entity_extraction_source: str | None = None,
    entity_extraction_source_char_count: str | None = None,
    display_preview_char_count: str | None = None,
    draft_extracted_order_ids: str | None,
    draft_extracted_product_ids: str | None,
    draft_extracted_tracking_code: str | None,
    draft_extracted_tracking_carrier: str | None = None,
    draft_extracted_iban: str | None = None,
    draft_extracted_iban_masked: str | None = None,
    draft_entity_warnings_summary: str | None,
) -> list[str]:
    """Markdown bullets for first-turn draft entities (operator console draft block)."""
    has_any = any(
        (
            draft_extracted_order_ids,
            draft_extracted_product_ids,
            draft_extracted_tracking_code,
            draft_extracted_iban,
            draft_extracted_iban_masked,
            draft_entity_warnings_summary,
        ),
    )
    if not has_any and not draft_entity_source:
        return []
    carrier = draft_extracted_tracking_carrier or "—"
    warnings = draft_entity_warnings_summary or "—"
    draft_iban = iban_display_value(
        full_iban=draft_extracted_iban,
        masked_iban=draft_extracted_iban_masked,
    )
    source_label = entity_extraction_source or draft_entity_source or "—"
    lines = [
        f"- **Draft entity source:** {source_label}",
    ]
    if entity_extraction_source_char_count:
        lines.append(f"- **Source length:** {entity_extraction_source_char_count} chars")
    if display_preview_char_count:
        lines.append(f"- **Display preview length:** {display_preview_char_count} chars")
    lines.extend(
        [
            f"- **Draft order IDs:** {draft_extracted_order_ids or '—'}",
            f"- **Draft product IDs:** {draft_extracted_product_ids or '—'}",
            f"- **Draft tracking code:** {draft_extracted_tracking_code or '—'}",
            f"- **Draft Sheba / IBAN:** {draft_iban}",
            f"- **Draft carrier:** {carrier}",
            f"- **Draft warnings:** {warnings}",
        ],
    )
    return lines


def draft_entity_fallback_message() -> str:
    return "No first-turn draft entities extracted from original_vendor_issue_preview."
