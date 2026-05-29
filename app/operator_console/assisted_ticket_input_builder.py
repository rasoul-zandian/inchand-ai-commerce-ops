"""Canonical operator-ticket and graph-input construction for assisted mode."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.config import AppSettings, get_settings
from app.evals.first_turn_draft_context import (
    resolve_first_turn_text_sources_from_ticket,
)
from app.live_feed.open_ticket_snapshot import (
    build_open_ticket_snapshot,
    extract_full_first_vendor_message,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.manual_chat_models import (
    AI_ASSISTED_DRAFT_SOURCE,
    ManualChatMessage,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.multi_turn_ticket_context import (
    build_multi_turn_context,
    is_closed_conversation_snapshot,
    multi_turn_context_metadata_row,
    resolve_extraction_text_for_context,
    resolve_response_target_text,
    ticket_status_gating_metadata,
)

AssistedSourceMode = Literal[
    "historical_replay",
    "live_api_feed",
    "manual_sandbox_chat",
]

AI_GENERATED_METADATA_KEY = "is_ai_generated"
AI_SOURCE_METADATA_KEY = "source"


@dataclass(frozen=True)
class AssistedGraphInputBundle:
    """Ticket + optional conversation snapshot passed into the sandbox graph."""

    ticket: OperatorTicket
    conversation_snapshot: ConversationTicketSnapshot | None
    display_snapshot: ConversationTicketSnapshot | None
    source_mode: AssistedSourceMode
    ticket_label_source: str | None
    safe_metadata: dict[str, Any]
    first_turn_text: str
    response_target_seller_text: str
    entity_extraction_text: str
    entity_extraction_source: str
    multi_turn_active: bool


def is_ai_generated_conversation_message(message: ConversationMessage) -> bool:
    meta = message.metadata if isinstance(message.metadata, dict) else {}
    if meta.get(AI_GENERATED_METADATA_KEY) is True:
        return True
    return str(meta.get(AI_SOURCE_METADATA_KEY) or "") == AI_ASSISTED_DRAFT_SOURCE


def is_human_support_message(message: ConversationMessage) -> bool:
    sender = message.sender_type.strip().lower()
    if sender not in {"support_agent", "finance_agent"}:
        return False
    return not is_ai_generated_conversation_message(message)


def manual_messages_to_conversation_messages(
    messages: Sequence[ManualChatMessage],
) -> list[ConversationMessage]:
    """Convert manual chat messages with AI/human metadata preserved."""
    result: list[ConversationMessage] = []
    for message in messages:
        metadata: dict[str, Any] = {}
        if message.is_ai_generated:
            metadata[AI_GENERATED_METADATA_KEY] = True
        if message.source:
            metadata[AI_SOURCE_METADATA_KEY] = message.source
        if message.draft_provider:
            metadata["draft_provider"] = message.draft_provider
        from datetime import datetime

        result.append(
            ConversationMessage(
                message_id=message.message_id,
                sender_type=message.sender_type,
                text=message.text,
                timestamp=datetime.fromisoformat(message.created_at.replace("Z", "+00:00")),
                metadata=metadata,
            ),
        )
    return result


def build_conversation_snapshot_from_manual_messages(
    messages: Sequence[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None = None,
    shop_id: str | None = None,
    status: str = "open",
) -> ConversationTicketSnapshot:
    if not messages:
        raise ValueError("manual chat requires at least one message")
    conv_messages = manual_messages_to_conversation_messages(messages)
    metadata: dict[str, Any] = {
        "source_system": "manual_sandbox_chat",
        "ticket_label_source": "manual_unset" if ticket_label is None else "manual_selected",
    }
    if shop_id and shop_id.strip():
        metadata["shop_id"] = shop_id.strip()
        metadata["shop_identity_available"] = True
    else:
        metadata["shop_identity_available"] = False
    normalized_status = (status or "open").strip() or "open"
    metadata["status"] = normalized_status
    effective_label = (ticket_label or "unknown").strip()
    return ConversationTicketSnapshot(
        room_id=room_id.strip(),
        ticket_label=effective_label,
        status=normalized_status,
        messages=conv_messages,
        metadata=metadata,
    )


def _safe_metadata_from_snapshot(
    snapshot: ConversationTicketSnapshot | None,
    *,
    source_mode: AssistedSourceMode,
    ticket_label_source: str | None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"source_system": source_mode}
    if ticket_label_source:
        meta["ticket_label_source"] = ticket_label_source
    if snapshot is not None and isinstance(snapshot.metadata, dict):
        for key in (
            "shop_id",
            "seller_id",
            "shop_name",
            "shop_identity_available",
            "shop_id_present",
            "seller_id_present",
            "shop_name_present",
            "shop_id_source",
            "seller_id_source",
            "shop_name_source",
            "ticket_label_source",
            "source_system",
            "status",
        ):
            if key in snapshot.metadata and snapshot.metadata[key] is not None:
                meta[key] = snapshot.metadata[key]
    if snapshot is not None:
        status_value = snapshot.status or meta.get("status")
        if status_value is not None:
            meta["status"] = str(status_value).strip()
        meta.update(ticket_status_gating_metadata(snapshot.status or meta.get("status")))
    return meta


def should_use_multi_turn_conversation_snapshot(
    snapshot: ConversationTicketSnapshot | None,
    *,
    settings: AppSettings,
    source_mode: AssistedSourceMode,
) -> bool:
    """Use multi-turn graph path only when thread context materially differs from first-turn."""
    if not settings.multi_turn_context_enabled or snapshot is None:
        return False
    if source_mode == "historical_replay":
        return False
    human_support = any(is_human_support_message(message) for message in snapshot.messages)
    seller_count = sum(
        1 for message in snapshot.messages if message.sender_type.strip().lower() == "seller"
    )
    return human_support or seller_count > 1


def build_operator_ticket_from_open_snapshot(
    snapshot: ConversationTicketSnapshot,
    *,
    shop_id: str | None = None,
    ticket_label: str | None = None,
    route_label: str | None = None,
    ticket_label_source: str | None = None,
) -> OperatorTicket:
    """Build operator ticket fields from a conversation snapshot (live/manual display path)."""
    open_snap = build_open_ticket_snapshot(snapshot)
    full_first = extract_full_first_vendor_message(snapshot)
    effective_shop = shop_id
    effective_seller_id: str | None = None
    effective_shop_name: str | None = None
    identity_available: bool | None = None
    if not effective_shop and isinstance(snapshot.metadata, dict):
        raw_shop = snapshot.metadata.get("shop_id")
        if raw_shop is not None:
            effective_shop = str(raw_shop).strip() or None
    if isinstance(snapshot.metadata, dict):
        raw_seller_id = snapshot.metadata.get("seller_id")
        raw_shop_name = snapshot.metadata.get("shop_name")
        if raw_seller_id is not None:
            effective_seller_id = str(raw_seller_id).strip() or None
        if raw_shop_name is not None:
            effective_shop_name = str(raw_shop_name).strip() or None
        if snapshot.metadata.get("shop_identity_available") is not None:
            identity_available = bool(snapshot.metadata.get("shop_identity_available"))

    label_for_ticket = ticket_label
    if label_for_ticket is None and ticket_label_source != "manual_unset":
        label_for_ticket = snapshot.ticket_label if snapshot.ticket_label != "unknown" else None

    return OperatorTicket(
        room_id=snapshot.room_id,
        ticket_label=label_for_ticket,
        route_label=route_label,
        shop_id=effective_shop,
        seller_id=effective_seller_id,
        shop_name=effective_shop_name,
        shop_identity_available=(
            identity_available
            if identity_available is not None
            else bool(effective_shop or effective_seller_id or effective_shop_name)
        ),
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=open_snap.open_ticket_preview,
        open_ticket_preview=open_snap.open_ticket_preview,
        original_vendor_issue_preview=open_snap.original_vendor_issue_preview,
        latest_vendor_message=open_snap.latest_vendor_message,
        recent_context_preview=open_snap.recent_context_preview,
        full_first_vendor_message_text=full_first,
    )


def build_operator_ticket_from_manual_chat(
    messages: Sequence[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None = None,
    shop_id: str | None = None,
    status: str = "open",
) -> tuple[OperatorTicket, ConversationTicketSnapshot]:
    snapshot = build_conversation_snapshot_from_manual_messages(
        messages,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        status=status,
    )
    label_source = str(snapshot.metadata.get("ticket_label_source") or "")
    ticket = build_operator_ticket_from_open_snapshot(
        snapshot,
        shop_id=shop_id,
        ticket_label=ticket_label,
        ticket_label_source=label_source,
    )
    return ticket, snapshot


def build_operator_ticket_from_replay_row(
    ticket: OperatorTicket,
) -> OperatorTicket:
    """Replay tickets are already HITL-shaped; return unchanged."""
    return ticket


def build_assisted_graph_input_from_operator_ticket(
    ticket: OperatorTicket,
    *,
    conversation_snapshot: ConversationTicketSnapshot | None = None,
    source_mode: AssistedSourceMode = "historical_replay",
    settings: AppSettings | None = None,
) -> AssistedGraphInputBundle:
    """Resolve first-turn vs multi-turn graph inputs consistently across console modes."""
    cfg = settings or get_settings()
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    label_source = None
    if conversation_snapshot is not None and isinstance(conversation_snapshot.metadata, dict):
        label_source = conversation_snapshot.metadata.get("ticket_label_source")

    multi_active = should_use_multi_turn_conversation_snapshot(
        conversation_snapshot,
        settings=cfg,
        source_mode=source_mode,
    )
    force_closed_gating = (
        conversation_snapshot is not None
        and cfg.multi_turn_context_enabled
        and is_closed_conversation_snapshot(conversation_snapshot)
    )
    use_graph_snapshot = multi_active or force_closed_gating
    graph_snapshot = conversation_snapshot if use_graph_snapshot else None

    response_target = sources.display_text
    extraction_text = sources.extraction_text
    multi_meta: dict[str, Any] = {}

    if graph_snapshot is not None and (multi_active or force_closed_gating):
        multi_ctx = build_multi_turn_context(graph_snapshot, settings=cfg)
        multi_meta = multi_turn_context_metadata_row(multi_ctx)
        if multi_active:
            response_target = resolve_response_target_text(
                context=multi_ctx,
                fallback_first_turn=sources.display_text,
                multi_turn_enabled=True,
            )
            extraction_text = resolve_extraction_text_for_context(
                context=multi_ctx,
                fallback_extraction=sources.extraction_text,
                multi_turn_enabled=True,
            )

    safe_metadata = _safe_metadata_from_snapshot(
        conversation_snapshot,
        source_mode=source_mode,
        ticket_label_source=str(label_source) if label_source else None,
    )
    safe_metadata.update(multi_meta)

    return AssistedGraphInputBundle(
        ticket=ticket,
        conversation_snapshot=graph_snapshot,
        display_snapshot=conversation_snapshot,
        source_mode=source_mode,
        ticket_label_source=str(label_source) if label_source else None,
        safe_metadata=safe_metadata,
        first_turn_text=sources.display_text,
        response_target_seller_text=response_target,
        entity_extraction_text=extraction_text,
        entity_extraction_source=sources.entity_extraction_source,
        multi_turn_active=multi_active or force_closed_gating,
    )


def assisted_input_parity_debug_row(bundle: AssistedGraphInputBundle) -> dict[str, Any]:
    """Safe debug fields for operator console (no raw prompts)."""
    display = bundle.display_snapshot
    return {
        "source_system": bundle.source_mode,
        "ticket_label": bundle.ticket.ticket_label,
        "ticket_label_source": bundle.ticket_label_source,
        "route_label": bundle.ticket.route_label,
        "conversation_snapshot_message_count": (
            len(display.messages) if display is not None else 0
        ),
        "graph_conversation_snapshot_used": bundle.conversation_snapshot is not None,
        "multi_turn_active": bundle.multi_turn_active,
        "response_target_seller_text_length": len(bundle.response_target_seller_text),
        "entity_extraction_text_length": len(bundle.entity_extraction_text),
        "entity_extraction_source": bundle.entity_extraction_source,
        "original_vendor_issue_preview_length": len(
            (bundle.ticket.original_vendor_issue_preview or ""),
        ),
        "full_first_vendor_message_text_length": len(
            (bundle.ticket.full_first_vendor_message_text or ""),
        ),
        "latest_sender_type": bundle.safe_metadata.get("multi_turn_latest_sender_type"),
        "shop_id_present": bool(bundle.ticket.shop_id),
        "seller_id_present": bool(bundle.ticket.seller_id),
        "shop_name_present": bool(bundle.ticket.shop_name),
        "shop_identity_available": bool(
            bundle.ticket.shop_identity_available
            if bundle.ticket.shop_identity_available is not None
            else (
                bundle.safe_metadata.get("shop_identity_available")
                or bundle.ticket.shop_id
                or bundle.ticket.seller_id
                or bundle.ticket.shop_name
            )
        ),
        "runtime_shop_identity_available": bool(
            bundle.ticket.shop_identity_available
            if bundle.ticket.shop_identity_available is not None
            else (bundle.ticket.shop_id or bundle.ticket.seller_id or bundle.ticket.shop_name)
        ),
        "runtime_shop_id_present": bool(bundle.ticket.shop_id),
        "knowledge_hints_enabled": None,
        "multi_turn_context_enabled": bundle.safe_metadata.get("multi_turn_context_enabled"),
    }


def parity_debug_row_with_settings(
    bundle: AssistedGraphInputBundle,
    *,
    settings: AppSettings,
) -> dict[str, Any]:
    row = assisted_input_parity_debug_row(bundle)
    row["knowledge_hints_enabled"] = settings.operator_agentic_assisted_knowledge_hints_enabled
    row["multi_turn_context_enabled"] = settings.multi_turn_context_enabled
    return row
