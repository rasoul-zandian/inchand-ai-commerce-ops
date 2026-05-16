"""Map validated conversation snapshots to offline workflow-ready inputs."""

from __future__ import annotations

from typing import Any, cast

from app.state.commerce_state import CommerceAIState
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    conversation_to_plain_text,
)

_EXCLUDED_METADATA_KEYS = frozenset(
    {
        "api_key",
        "secret",
        "password",
        "token",
        "attachment",
        "attachments",
        "raw_export",
        "mapping_table",
    }
)

_TRANSCRIPT_HEADER = "Conversation transcript:\n"


def _unique_sender_types_in_order(snapshot: ConversationTicketSnapshot) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for message in snapshot.messages:
        if message.sender_type not in seen:
            seen.add(message.sender_type)
            ordered.append(message.sender_type)
    return ordered


def conversation_snapshot_to_workflow_input(
    snapshot: ConversationTicketSnapshot,
) -> dict[str, Any]:
    """Build a safe workflow input dict from a validated conversation snapshot."""
    transcript = conversation_to_plain_text(snapshot)
    user_input = f"{_TRANSCRIPT_HEADER}{transcript}"

    workflow_metadata: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "ticket_subtype": snapshot.ticket_subtype,
        "seller_id": snapshot.seller_id,
        "status": snapshot.status,
        "message_count": len(snapshot.messages),
        "sender_types": _unique_sender_types_in_order(snapshot),
        "has_final_resolution": bool(snapshot.final_resolution),
    }

    workflow_state_snapshot: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "ticket_subtype": snapshot.ticket_subtype,
        "seller_id": snapshot.seller_id,
        "conversation_transcript": transcript,
        "final_resolution": dict(snapshot.final_resolution),
    }

    return {
        "user_input": user_input,
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "ticket_subtype": snapshot.ticket_subtype,
        "workflow_metadata": workflow_metadata,
        "workflow_state_snapshot": workflow_state_snapshot,
    }


def resolve_ticket_context_from_state(data: dict[str, Any]) -> dict[str, str | None]:
    """Read room/ticket topic fields from top-level state or nested workflow snapshot."""
    nested = data.get("workflow_state_snapshot")
    snapshot = nested if isinstance(nested, dict) else {}

    def _pick(key: str) -> str | None:
        top = data.get(key)
        if isinstance(top, str) and top.strip():
            return top.strip()
        nested_value = snapshot.get(key)
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()
        return None

    return {
        "room_id": _pick("room_id"),
        "ticket_label": _pick("ticket_label"),
        "ticket_subtype": _pick("ticket_subtype"),
    }


def apply_ticket_context_to_state(state: CommerceAIState) -> CommerceAIState:
    """Promote ticket_label/room_id onto state from top-level or workflow_state_snapshot."""
    data = dict(state)
    context = resolve_ticket_context_from_state(data)
    for key, value in context.items():
        if value is not None:
            data[key] = value
    if not isinstance(data.get("workflow_state_snapshot"), dict):
        data["workflow_state_snapshot"] = {}
    return cast(CommerceAIState, data)


def map_conversation_snapshots_to_workflow_inputs(
    snapshots: list[ConversationTicketSnapshot],
) -> list[dict[str, Any]]:
    """Map a batch of snapshots to workflow-ready input dicts."""
    return [conversation_snapshot_to_workflow_input(snapshot) for snapshot in snapshots]
