"""Compare assisted-mode graph inputs across console data sources (safe metadata only)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.config import AppSettings, get_settings
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.assisted_ticket_input_builder import (
    AssistedGraphInputBundle,
    build_assisted_graph_input_from_operator_ticket,
    build_operator_ticket_from_manual_chat,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.manual_chat_models import ManualChatMessage
from app.operator_console.manual_chat_sandbox import append_manual_chat_message
from app.tickets.conversation_models import ConversationTicketSnapshot


def text_fingerprint(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ComparedAssistedField:
    field_name: str
    historical_value: Any
    manual_value: Any
    match: bool
    note: str | None = None


@dataclass(frozen=True)
class AssistedInputSnapshot:
    room_id: str
    source_system: str
    ticket_label: str | None
    route_label: str | None
    ticket_label_source: str | None
    first_turn_text_length: int
    first_turn_text_fingerprint: str | None
    response_target_seller_text_length: int
    response_target_seller_text_fingerprint: str | None
    entity_extraction_text_length: int
    entity_extraction_text_fingerprint: str | None
    entity_extraction_source: str | None
    original_vendor_issue_preview_length: int
    original_vendor_issue_preview_fingerprint: str | None
    full_first_vendor_message_text_length: int
    full_first_vendor_message_text_fingerprint: str | None
    conversation_snapshot_message_count: int
    graph_conversation_snapshot_used: bool
    latest_sender_type: str | None
    safe_metadata_keys: tuple[str, ...]
    shop_id_present: bool
    knowledge_hints_enabled: bool
    multi_turn_context_enabled: bool
    multi_turn_active: bool
    provider: str
    draft_provider: str | None = None
    detected_intent: str | None = None
    suggested_action: str | None = None
    actionability_actionable: bool | None = None
    order_id_count: int | None = None
    product_id_count: int | None = None
    knowledge_hint_document_types: tuple[str, ...] = ()
    draft_fingerprint: str | None = None
    reflection_issue_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssistedInputComparison:
    room_id: str
    fields: tuple[ComparedAssistedField, ...] = ()
    all_match: bool = True
    explainable_differences: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _snapshot_from_bundle(
    bundle: AssistedGraphInputBundle,
    *,
    settings: AppSettings,
    graph_result: AgenticSandboxPreviewResult | None = None,
) -> AssistedInputSnapshot:
    ticket = bundle.ticket
    graph = graph_result
    return AssistedInputSnapshot(
        room_id=ticket.room_id,
        source_system=bundle.source_mode,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
        ticket_label_source=bundle.ticket_label_source,
        first_turn_text_length=len(bundle.first_turn_text),
        first_turn_text_fingerprint=text_fingerprint(bundle.first_turn_text),
        response_target_seller_text_length=len(bundle.response_target_seller_text),
        response_target_seller_text_fingerprint=text_fingerprint(
            bundle.response_target_seller_text
        ),
        entity_extraction_text_length=len(bundle.entity_extraction_text),
        entity_extraction_text_fingerprint=text_fingerprint(bundle.entity_extraction_text),
        entity_extraction_source=bundle.entity_extraction_source,
        original_vendor_issue_preview_length=len(ticket.original_vendor_issue_preview or ""),
        original_vendor_issue_preview_fingerprint=text_fingerprint(
            ticket.original_vendor_issue_preview,
        ),
        full_first_vendor_message_text_length=len(ticket.full_first_vendor_message_text or ""),
        full_first_vendor_message_text_fingerprint=text_fingerprint(
            ticket.full_first_vendor_message_text,
        ),
        conversation_snapshot_message_count=(
            len(bundle.display_snapshot.messages) if bundle.display_snapshot else 0
        ),
        graph_conversation_snapshot_used=bundle.conversation_snapshot is not None,
        latest_sender_type=bundle.safe_metadata.get("multi_turn_latest_sender_type"),
        safe_metadata_keys=tuple(sorted(bundle.safe_metadata.keys())),
        shop_id_present=bool(ticket.shop_id),
        knowledge_hints_enabled=settings.operator_agentic_assisted_knowledge_hints_enabled,
        multi_turn_context_enabled=settings.multi_turn_context_enabled,
        multi_turn_active=bundle.multi_turn_active,
        provider=settings.operator_agentic_assisted_provider,
        draft_provider=graph.draft_provider if graph else None,
        detected_intent=graph.detected_intent if graph else None,
        suggested_action=graph.suggested_action if graph else None,
        actionability_actionable=graph.actionability_actionable if graph else None,
        order_id_count=graph.order_id_count if graph else None,
        product_id_count=graph.product_id_count if graph else None,
        knowledge_hint_document_types=graph.knowledge_hint_document_types if graph else (),
        draft_fingerprint=text_fingerprint(graph.draft_reply if graph else None),
        reflection_issue_types=graph.reflection_issue_types if graph else (),
    )


def build_assisted_input_snapshot_from_historical(
    ticket: OperatorTicket,
    *,
    conversation_snapshot: ConversationTicketSnapshot | None = None,
    settings: AppSettings | None = None,
    graph_result: AgenticSandboxPreviewResult | None = None,
) -> AssistedInputSnapshot:
    cfg = settings or get_settings()
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=conversation_snapshot,
        source_mode="historical_replay",
        settings=cfg,
    )
    return _snapshot_from_bundle(bundle, settings=cfg, graph_result=graph_result)


def build_assisted_input_snapshot_from_manual(
    ticket: OperatorTicket,
    *,
    conversation_snapshot: ConversationTicketSnapshot,
    settings: AppSettings | None = None,
    graph_result: AgenticSandboxPreviewResult | None = None,
) -> AssistedInputSnapshot:
    cfg = settings or get_settings()
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=conversation_snapshot,
        source_mode="manual_sandbox_chat",
        settings=cfg,
    )
    return _snapshot_from_bundle(bundle, settings=cfg, graph_result=graph_result)


def _compare_value(field_name: str, left: Any, right: Any) -> ComparedAssistedField:
    return ComparedAssistedField(
        field_name=field_name,
        historical_value=left,
        manual_value=right,
        match=left == right,
    )


def compare_assisted_input_snapshots(
    historical: AssistedInputSnapshot,
    manual: AssistedInputSnapshot,
) -> AssistedInputComparison:
    field_names = (
        "ticket_label",
        "route_label",
        "ticket_label_source",
        "first_turn_text_fingerprint",
        "response_target_seller_text_fingerprint",
        "entity_extraction_text_fingerprint",
        "entity_extraction_source",
        "original_vendor_issue_preview_fingerprint",
        "full_first_vendor_message_text_fingerprint",
        "graph_conversation_snapshot_used",
        "multi_turn_active",
        "latest_sender_type",
        "shop_id_present",
        "knowledge_hints_enabled",
        "multi_turn_context_enabled",
        "detected_intent",
        "suggested_action",
        "actionability_actionable",
        "order_id_count",
        "product_id_count",
        "knowledge_hint_document_types",
        "draft_fingerprint",
    )
    compared: list[ComparedAssistedField] = []
    explainable: list[str] = []
    for name in field_names:
        left = getattr(historical, name)
        right = getattr(manual, name)
        row = _compare_value(name, left, right)
        compared.append(row)
        if not row.match:
            if name == "route_label" and historical.route_label and manual.route_label is None:
                explainable.append("manual_sandbox_has_no_replay_route_label")
            elif name == "ticket_label" and historical.ticket_label != manual.ticket_label:
                explainable.append("ticket_label_selection_mismatch")
            elif name in {
                "graph_conversation_snapshot_used",
                "multi_turn_active",
                "response_target_seller_text_fingerprint",
            }:
                explainable.append("multi_turn_vs_first_turn_path_difference")
            elif name == "original_vendor_issue_preview_fingerprint":
                explainable.append("preview_truncation_or_redaction_difference")
            elif name == "full_first_vendor_message_text_fingerprint":
                explainable.append("missing_full_first_vendor_message_on_manual_path")

    all_match = all(row.match for row in compared)
    notes: list[str] = []
    if historical.source_system != manual.source_system:
        notes.append("source_system differs by design")
    if historical.conversation_snapshot_message_count != manual.conversation_snapshot_message_count:
        notes.append("conversation_message_count_may_differ_for_thread_context")

    return AssistedInputComparison(
        room_id=historical.room_id,
        fields=tuple(compared),
        all_match=all_match,
        explainable_differences=tuple(explainable),
        notes=tuple(notes),
    )


def build_manual_ticket_for_comparison(
    manual_text: str,
    *,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None = None,
) -> tuple[OperatorTicket, ConversationTicketSnapshot]:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text=manual_text)
    return build_operator_ticket_from_manual_chat(
        messages,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
    )


def package_graph_summary(package: AgenticAssistedPackage) -> dict[str, Any]:
    graph = package.graph
    return {
        "room_id": package.room_id,
        "detected_intent": graph.detected_intent,
        "suggested_action": graph.suggested_action,
        "actionability_actionable": graph.actionability_actionable,
        "order_id_count": graph.order_id_count,
        "product_id_count": graph.product_id_count,
        "knowledge_hint_document_types": list(graph.knowledge_hint_document_types),
        "draft_char_count": graph.draft_char_count,
        "draft_fingerprint": text_fingerprint(graph.draft_reply),
        "reflection_issue_types": list(graph.reflection_issue_types),
        "reflection_rewrite_applied": graph.reflection_rewrite_applied,
        "multi_turn_should_generate_draft": graph.multi_turn_should_generate_draft,
        "multi_turn_skip_reason": graph.multi_turn_skip_reason,
    }


def comparison_to_dict(comparison: AssistedInputComparison) -> dict[str, Any]:
    return {
        "room_id": comparison.room_id,
        "all_match": comparison.all_match,
        "explainable_differences": list(comparison.explainable_differences),
        "notes": list(comparison.notes),
        "fields": [
            {
                "field_name": row.field_name,
                "historical_value": row.historical_value,
                "manual_value": row.manual_value,
                "match": row.match,
                "note": row.note,
            }
            for row in comparison.fields
        ],
    }


def snapshot_to_dict(snapshot: AssistedInputSnapshot) -> dict[str, Any]:
    return {
        "room_id": snapshot.room_id,
        "source_system": snapshot.source_system,
        "ticket_label": snapshot.ticket_label,
        "route_label": snapshot.route_label,
        "ticket_label_source": snapshot.ticket_label_source,
        "first_turn_text_length": snapshot.first_turn_text_length,
        "first_turn_text_fingerprint": snapshot.first_turn_text_fingerprint,
        "response_target_seller_text_length": snapshot.response_target_seller_text_length,
        "response_target_seller_text_fingerprint": snapshot.response_target_seller_text_fingerprint,
        "entity_extraction_text_length": snapshot.entity_extraction_text_length,
        "entity_extraction_text_fingerprint": snapshot.entity_extraction_text_fingerprint,
        "entity_extraction_source": snapshot.entity_extraction_source,
        "original_vendor_issue_preview_length": snapshot.original_vendor_issue_preview_length,
        "original_vendor_issue_preview_fingerprint": (
            snapshot.original_vendor_issue_preview_fingerprint
        ),
        "full_first_vendor_message_text_length": (snapshot.full_first_vendor_message_text_length),
        "full_first_vendor_message_text_fingerprint": (
            snapshot.full_first_vendor_message_text_fingerprint
        ),
        "conversation_snapshot_message_count": snapshot.conversation_snapshot_message_count,
        "graph_conversation_snapshot_used": snapshot.graph_conversation_snapshot_used,
        "latest_sender_type": snapshot.latest_sender_type,
        "safe_metadata_keys": list(snapshot.safe_metadata_keys),
        "shop_id_present": snapshot.shop_id_present,
        "knowledge_hints_enabled": snapshot.knowledge_hints_enabled,
        "multi_turn_context_enabled": snapshot.multi_turn_context_enabled,
        "multi_turn_active": snapshot.multi_turn_active,
        "provider": snapshot.provider,
        "draft_provider": snapshot.draft_provider,
        "detected_intent": snapshot.detected_intent,
        "suggested_action": snapshot.suggested_action,
        "actionability_actionable": snapshot.actionability_actionable,
        "order_id_count": snapshot.order_id_count,
        "product_id_count": snapshot.product_id_count,
        "knowledge_hint_document_types": list(snapshot.knowledge_hint_document_types),
        "draft_fingerprint": snapshot.draft_fingerprint,
        "reflection_issue_types": list(snapshot.reflection_issue_types),
    }
