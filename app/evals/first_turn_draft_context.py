"""First-turn-only draft context — intent, entities, and hints from initial seller message only."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import (
    KnowledgeHint,
    KnowledgeRetrievalFn,
    fetch_knowledge_hints_for_ticket,
)
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
from app.workflows.suggested_action_taxonomy import map_intent_to_suggested_action
from app.workflows.vendor_ticket_intent_detection import (
    VendorTicketIntentDetectionResult,
    detect_vendor_ticket_intent,
)

ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE = "original_vendor_issue_preview"
ENTITY_SOURCE_FULL_FIRST_VENDOR = "full_first_vendor_message_text"

FIRST_TURN_EXCLUDED_THREAD_FIELDS: tuple[str, ...] = (
    "snapshot_before_reply.latest_vendor_message",
    "snapshot_before_reply.recent_context_preview",
    "open_ticket_preview",
    "ticket_text_preview",
    "latest_vendor_message",
    "recent_context_preview",
)


@dataclass(frozen=True)
class FirstTurnTextSources:
    """Display vs extraction inputs for first-turn-only mode."""

    display_text: str
    extraction_text: str
    entity_extraction_source: str
    entity_extraction_source_char_count: int
    display_preview_char_count: int


@dataclass(frozen=True)
class FirstTurnDraftContext:
    """Isolated inputs for first-turn draft generation (no thread leakage)."""

    first_turn_text: str
    first_turn_intent: VendorTicketIntentDetectionResult
    first_turn_entities: OperationalEntityExtractionResult
    first_turn_policy_hints: tuple[KnowledgeHint, ...]
    excluded_thread_fields: tuple[str, ...]
    suggested_action: str
    suggested_action_reason: str | None = None
    entity_source: str = ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    entity_extraction_source: str = ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    entity_extraction_source_char_count: int = 0
    display_preview_char_count: int = 0


def first_turn_text_from_case(case: Mapping[str, Any]) -> str:
    """Return only ``original_vendor_issue_preview`` from a benchmark case."""
    snap = case.get("snapshot_before_reply")
    if not isinstance(snap, Mapping):
        return ""
    raw = snap.get("original_vendor_issue_preview")
    if isinstance(raw, str):
        return raw.strip()
    return ""


def full_first_vendor_message_from_case(case: Mapping[str, Any]) -> str:
    """Optional full first seller message on benchmark cases (internal extraction only)."""
    snap = case.get("snapshot_before_reply")
    if not isinstance(snap, Mapping):
        return ""
    raw = snap.get("full_first_vendor_message_text")
    if isinstance(raw, str):
        return raw.strip()
    return ""


def resolve_first_turn_text_sources_from_ticket(ticket: OperatorTicket) -> FirstTurnTextSources:
    """Separate truncated display preview from full first-turn extraction text."""
    display = first_turn_text_from_ticket(ticket)
    full = (ticket.full_first_vendor_message_text or "").strip()
    extraction = full if full else display
    source = ENTITY_SOURCE_FULL_FIRST_VENDOR if full else ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    return FirstTurnTextSources(
        display_text=display,
        extraction_text=extraction,
        entity_extraction_source=source,
        entity_extraction_source_char_count=len(extraction),
        display_preview_char_count=len(display),
    )


def resolve_first_turn_text_sources_from_case(case: Mapping[str, Any]) -> FirstTurnTextSources:
    display = first_turn_text_from_case(case)
    full = full_first_vendor_message_from_case(case)
    extraction = full if full else display
    source = ENTITY_SOURCE_FULL_FIRST_VENDOR if full else ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    return FirstTurnTextSources(
        display_text=display,
        extraction_text=extraction,
        entity_extraction_source=source,
        entity_extraction_source_char_count=len(extraction),
        display_preview_char_count=len(display),
    )


def first_turn_text_from_ticket(ticket: OperatorTicket) -> str:
    """Return only the operator ticket's initial seller issue preview (display/prompt)."""
    raw = ticket.original_vendor_issue_preview
    if isinstance(raw, str):
        return raw.strip()
    return ""


def first_turn_extraction_text_from_ticket(ticket: OperatorTicket) -> str:
    """Text used for operational entity extraction (full first seller message when available)."""
    return resolve_first_turn_text_sources_from_ticket(ticket).extraction_text


def text_sources_from_context(ctx: FirstTurnDraftContext) -> FirstTurnTextSources:
    """Rebuild text source metadata from an assembled first-turn context."""
    return FirstTurnTextSources(
        display_text=ctx.first_turn_text,
        extraction_text=ctx.first_turn_text,
        entity_extraction_source=ctx.entity_extraction_source,
        entity_extraction_source_char_count=ctx.entity_extraction_source_char_count,
        display_preview_char_count=ctx.display_preview_char_count,
    )


def draft_entity_preview_fields(
    entities: OperationalEntityExtractionResult,
    *,
    sources: FirstTurnTextSources | None = None,
    context: FirstTurnDraftContext | None = None,
) -> dict[str, str | int | None]:
    """Map first-turn extraction to operator draft preview fields (not AI assist globals)."""
    if context is not None:
        src = text_sources_from_context(context)
    elif sources is not None:
        src = sources
    else:
        msg = "draft_entity_preview_fields requires sources or context"
        raise ValueError(msg)
    order_csv = ",".join(entities.order_ids) if entities.order_ids else None
    product_csv = ",".join(entities.product_ids) if entities.product_ids else None
    carrier = entities.primary_tracking_carrier
    return {
        "draft_entity_source": src.entity_extraction_source,
        "entity_source": src.entity_extraction_source,
        "entity_extraction_source": src.entity_extraction_source,
        "entity_extraction_source_char_count": src.entity_extraction_source_char_count,
        "display_preview_char_count": src.display_preview_char_count,
        "draft_extracted_order_ids": order_csv,
        "draft_extracted_product_ids": product_csv,
        "draft_extracted_tracking_code": entities.primary_tracking_code,
        "draft_extracted_iban": entities.primary_iban,
        "draft_extracted_iban_masked": entities.primary_iban_masked,
        "draft_entity_warnings_summary": entities.entity_warnings_summary,
        "draft_extracted_tracking_carrier": carrier.value if carrier else None,
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def intent_with_first_turn_entities(
    intent: VendorTicketIntentDetectionResult,
    entities: OperationalEntityExtractionResult,
) -> VendorTicketIntentDetectionResult:
    """Align intent aggregate entity fields with first-turn-only extraction."""
    carrier = entities.primary_tracking_carrier
    return replace(
        intent,
        extracted_order_ids=list(entities.order_ids),
        extracted_product_ids=list(entities.product_ids),
        extracted_tracking_code=entities.primary_tracking_code,
        extracted_tracking_carrier=carrier.value if carrier else None,
        extracted_iban=entities.primary_iban,
        extracted_iban_masked=entities.primary_iban_masked,
        entity_warnings_summary=entities.entity_warnings_summary,
    )


def hint_ticket_for_first_turn(
    *,
    room_id: str,
    ticket_label: str | None,
    route_label: str | None,
    first_turn_text: str,
    intent: VendorTicketIntentDetectionResult,
) -> OperatorTicket:
    """Minimal ticket for sandbox hints — no thread fields or precomputed entities."""
    order_ids_csv = ",".join(intent.extracted_order_ids) if intent.extracted_order_ids else None
    return OperatorTicket(
        room_id=room_id,
        ticket_label=ticket_label,
        route_label=route_label,
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=first_turn_text or None,
        latest_vendor_message=None,
        recent_context_preview=None,
        extracted_order_id=(intent.extracted_order_ids[0] if intent.extracted_order_ids else None),
        extracted_order_ids=order_ids_csv,
        extracted_tracking_code=intent.extracted_tracking_code,
        extracted_product_ids=(
            ",".join(intent.extracted_product_ids) if intent.extracted_product_ids else None
        ),
        extracted_tracking_carrier=intent.extracted_tracking_carrier,
        extracted_iban=intent.extracted_iban,
        extracted_iban_masked=intent.extracted_iban_masked,
        entity_warnings_summary=intent.entity_warnings_summary,
        detected_intent=intent.detected_intent,
    )


def build_first_turn_draft_context_from_case(
    case: Mapping[str, Any],
    *,
    settings: AppSettings | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
) -> FirstTurnDraftContext:
    """Build first-turn draft context from a benchmark case (ignores thread snapshot fields)."""
    cfg = settings or get_settings()
    sources = resolve_first_turn_text_sources_from_case(case)
    ticket_label = _optional_str(case.get("ticket_label"))
    route_label = _optional_str(case.get("route_label"))
    room_id = str(case.get("room_id") or "")

    intent_raw = detect_vendor_ticket_intent(
        sources.display_text,
        ticket_label=ticket_label,
        route_label=route_label,
    )
    entities = extract_operational_entities(sources.extraction_text)
    intent = intent_with_first_turn_entities(intent_raw, entities)
    normalized = (
        normalize_persian_arabic_digits(sources.display_text) if sources.display_text else ""
    )
    action_mapping = map_intent_to_suggested_action(
        intent.intent,
        entities=intent,
        normalized_text=normalized,
        ticket_label=ticket_label,
        route_label=route_label,
    )

    hints: tuple[KnowledgeHint, ...] = ()
    if cfg.knowledge_hints_enabled:
        hint_ticket = hint_ticket_for_first_turn(
            room_id=room_id,
            ticket_label=ticket_label,
            route_label=route_label,
            first_turn_text=sources.display_text,
            intent=intent,
        )
        hints = fetch_knowledge_hints_for_ticket(
            hint_ticket,
            settings=cfg,
            store=store,
            query_embedding_fn=query_embedding_fn,
            retrieve_fn=retrieve_fn,
            first_turn_only=True,
        )

    return FirstTurnDraftContext(
        first_turn_text=sources.display_text,
        first_turn_intent=intent,
        first_turn_entities=entities,
        first_turn_policy_hints=hints,
        excluded_thread_fields=FIRST_TURN_EXCLUDED_THREAD_FIELDS,
        suggested_action=action_mapping.action.value,
        suggested_action_reason=action_mapping.reason,
        entity_source=sources.entity_extraction_source,
        entity_extraction_source=sources.entity_extraction_source,
        entity_extraction_source_char_count=sources.entity_extraction_source_char_count,
        display_preview_char_count=sources.display_preview_char_count,
    )


def build_first_turn_draft_context_from_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    hints: Sequence[KnowledgeHint] | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
) -> FirstTurnDraftContext:
    """Build first-turn context from operator ticket (re-extract; ignore thread entities)."""
    cfg = settings or get_settings()
    sources = resolve_first_turn_text_sources_from_ticket(ticket)

    intent_raw = detect_vendor_ticket_intent(
        sources.display_text,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
    )
    entities = extract_operational_entities(sources.extraction_text)
    intent = intent_with_first_turn_entities(intent_raw, entities)
    normalized = (
        normalize_persian_arabic_digits(sources.display_text) if sources.display_text else ""
    )
    action_mapping = map_intent_to_suggested_action(
        intent.intent,
        entities=intent,
        normalized_text=normalized,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
    )

    policy_hints: tuple[KnowledgeHint, ...] = tuple(hints or ())
    if not policy_hints and cfg.knowledge_hints_enabled:
        hint_ticket = hint_ticket_for_first_turn(
            room_id=ticket.room_id,
            ticket_label=ticket.ticket_label,
            route_label=ticket.route_label,
            first_turn_text=sources.display_text,
            intent=intent,
        )
        policy_hints = fetch_knowledge_hints_for_ticket(
            hint_ticket,
            settings=cfg,
            store=store,
            query_embedding_fn=query_embedding_fn,
            retrieve_fn=retrieve_fn,
            first_turn_only=True,
        )

    return FirstTurnDraftContext(
        first_turn_text=sources.display_text,
        first_turn_intent=intent,
        first_turn_entities=entities,
        first_turn_policy_hints=policy_hints,
        excluded_thread_fields=FIRST_TURN_EXCLUDED_THREAD_FIELDS,
        suggested_action=action_mapping.action.value,
        suggested_action_reason=action_mapping.reason,
        entity_source=sources.entity_extraction_source,
        entity_extraction_source=sources.entity_extraction_source,
        entity_extraction_source_char_count=sources.entity_extraction_source_char_count,
        display_preview_char_count=sources.display_preview_char_count,
    )


def build_first_turn_draft_context(
    source: Mapping[str, Any] | OperatorTicket,
    *,
    settings: AppSettings | None = None,
    hints: Sequence[KnowledgeHint] | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> FirstTurnDraftContext | None:
    """Return isolated context for first_turn_only; None when mode allows thread context."""
    if mode != DraftGenerationMode.FIRST_TURN_ONLY:
        return None
    if isinstance(source, OperatorTicket):
        return build_first_turn_draft_context_from_ticket(
            source,
            settings=settings,
            hints=hints,
            retrieve_fn=retrieve_fn,
            query_embedding_fn=query_embedding_fn,
            store=store,
        )
    return build_first_turn_draft_context_from_case(
        source,
        settings=settings,
        retrieve_fn=retrieve_fn,
        query_embedding_fn=query_embedding_fn,
        store=store,
    )
