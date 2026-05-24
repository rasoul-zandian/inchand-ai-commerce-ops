"""First-vendor-only filtering for operator console listing (view layer only)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot

if TYPE_CHECKING:
    from app.operator_console.console_models import OperatorTicket

_INTERNAL_SENDER_TYPES = frozenset({"system", "unknown"})
_VENDOR_SENDER_TYPES = frozenset({"seller", "vendor"})
_SUPPORT_FIRST_SENDER_TYPES = frozenset({"support_agent", "finance_agent"})


def _normalize_sender_type(sender_type: str) -> str:
    return sender_type.strip().lower()


def first_meaningful_sender_type(
    messages: Sequence[ConversationMessage] | Sequence[Mapping[str, object]],
) -> str | None:
    """Return sender_type of the first non-internal message, or None if none."""
    for message in messages:
        if isinstance(message, ConversationMessage):
            raw_sender = message.sender_type
        elif isinstance(message, Mapping):
            raw_sender = message.get("sender_type")
        else:
            raw_sender = getattr(message, "sender_type", None)
        if not isinstance(raw_sender, str):
            continue
        sender = _normalize_sender_type(raw_sender)
        if sender in _INTERNAL_SENDER_TYPES:
            continue
        return sender
    return None


def is_first_vendor_ticket(snapshot: ConversationTicketSnapshot) -> bool:
    """True when the first non-internal/non-system message is from seller/vendor."""
    first = first_meaningful_sender_type(snapshot.messages)
    if first is None:
        return False
    if first in _SUPPORT_FIRST_SENDER_TYPES:
        return False
    return first in _VENDOR_SENDER_TYPES


def filter_first_vendor_tickets(
    tickets: Sequence[OperatorTicket],
    *,
    snapshot_index: Mapping[str, ConversationTicketSnapshot],
) -> list[OperatorTicket]:
    """Keep tickets whose room has a seller/vendor-first conversation in the snapshot index."""
    filtered: list[OperatorTicket] = []
    for ticket in tickets:
        snapshot = snapshot_index.get(ticket.room_id)
        if snapshot is None:
            continue
        if is_first_vendor_ticket(snapshot):
            filtered.append(ticket)
    return filtered


@dataclass(frozen=True)
class FirstVendorFilterStats:
    """Counts for operator console sidebar (listing filter only)."""

    total_loaded: int
    tickets_shown: int
    filter_active: bool


def apply_operator_first_vendor_filter(
    tickets: Sequence[OperatorTicket],
    *,
    snapshot_index: Mapping[str, ConversationTicketSnapshot],
    enabled: bool,
) -> tuple[list[OperatorTicket], FirstVendorFilterStats]:
    """Apply first-vendor filter when enabled; never mutates underlying ticket rows."""
    total_loaded = len(tickets)
    if not enabled:
        return list(tickets), FirstVendorFilterStats(
            total_loaded=total_loaded,
            tickets_shown=total_loaded,
            filter_active=False,
        )
    shown = filter_first_vendor_tickets(tickets, snapshot_index=snapshot_index)
    return shown, FirstVendorFilterStats(
        total_loaded=total_loaded,
        tickets_shown=len(shown),
        filter_active=True,
    )
