"""Lightweight models for live vendor ticket feed (internal read-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.tickets.conversation_models import ConversationTicketSnapshot


@dataclass(frozen=True)
class LiveVendorTicket:
    """One live vendor ticket (internal; user_input not shown in operator UI)."""

    room_id: str
    created_at: datetime | None
    updated_at: datetime | None
    ticket_label: str | None
    user_input: str
    assigned_department: str | None
    review_priority: str | None
    raw_payload: dict[str, Any] | None = None
    snapshot: ConversationTicketSnapshot | None = field(default=None, repr=False)

    def sort_key(self) -> tuple[datetime, str]:
        updated = self.updated_at or datetime.min.replace(tzinfo=UTC)
        return (updated, self.room_id)


@dataclass(frozen=True)
class LiveFeedCheckpoint:
    """Local JSON checkpoint for incremental live feed polling."""

    last_seen_updated_at: str | None = None
    seen_room_ids: list[str] = field(default_factory=list)
    last_poll_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_seen_updated_at": self.last_seen_updated_at,
            "seen_room_ids": list(self.seen_room_ids),
            "last_poll_at": self.last_poll_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveFeedCheckpoint:
        seen = data.get("seen_room_ids")
        room_ids = [str(item) for item in seen] if isinstance(seen, list) else []
        last_seen = data.get("last_seen_updated_at")
        last_poll = data.get("last_poll_at")
        return cls(
            last_seen_updated_at=str(last_seen) if last_seen else None,
            seen_room_ids=room_ids,
            last_poll_at=str(last_poll) if last_poll else None,
        )


@dataclass(frozen=True)
class LiveTicketBatch:
    """Result of one live feed poll."""

    tickets: list[LiveVendorTicket]
    operator_payloads: list[dict[str, Any]]
    fetched_count: int
    new_count: int
