"""Vendor ticket conversation contracts (export/import shapes; no live systems)."""

from app.tickets.conversation_models import (
    ALLOWED_SENDER_TYPES,
    ConversationMessage,
    ConversationTicketSnapshot,
    conversation_to_plain_text,
    parse_conversation_ticket_snapshot,
)
from app.tickets.workflow_mapping import (
    apply_ticket_context_to_state,
    conversation_snapshot_to_workflow_input,
    map_conversation_snapshots_to_workflow_inputs,
    resolve_ticket_context_from_state,
)

__all__ = [
    "ALLOWED_SENDER_TYPES",
    "ConversationMessage",
    "ConversationTicketSnapshot",
    "apply_ticket_context_to_state",
    "conversation_snapshot_to_workflow_input",
    "conversation_to_plain_text",
    "map_conversation_snapshots_to_workflow_inputs",
    "resolve_ticket_context_from_state",
    "parse_conversation_ticket_snapshot",
]
