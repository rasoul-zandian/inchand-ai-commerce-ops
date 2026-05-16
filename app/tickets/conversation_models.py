"""Typed contract for multi-message Inchand vendor-ticket chat room exports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

ALLOWED_SENDER_TYPES = frozenset({"seller", "support_agent", "finance_agent", "system", "unknown"})


def _non_empty_stripped(value: str, *, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


class ConversationMessage(BaseModel):
    message_id: str
    sender_type: str
    timestamp: datetime | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message_id")
    @classmethod
    def _validate_message_id(cls, value: str) -> str:
        return _non_empty_stripped(value, field_name="message_id")

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _non_empty_stripped(value, field_name="text")

    @field_validator("sender_type")
    @classmethod
    def _validate_sender_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SENDER_TYPES:
            allowed = ", ".join(sorted(ALLOWED_SENDER_TYPES))
            raise ValueError(f"sender_type must be one of: {allowed}")
        return normalized


class ConversationTicketSnapshot(BaseModel):
    room_id: str
    ticket_label: str
    ticket_subtype: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    closed_at: datetime | None = None
    seller_id: str | None = None
    final_resolution: dict[str, Any] = Field(default_factory=dict)
    messages: list[ConversationMessage]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("room_id")
    @classmethod
    def _validate_room_id(cls, value: str) -> str:
        return _non_empty_stripped(value, field_name="room_id")

    @field_validator("ticket_label")
    @classmethod
    def _validate_ticket_label(cls, value: str) -> str:
        return _non_empty_stripped(value, field_name="ticket_label")

    @field_validator("messages")
    @classmethod
    def _validate_messages_non_empty(
        cls, value: list[ConversationMessage]
    ) -> list[ConversationMessage]:
        if not value:
            raise ValueError("messages must contain at least one message")
        return value


def parse_conversation_ticket_snapshot(
    payload: dict[str, Any] | str,
) -> ConversationTicketSnapshot:
    """Parse a JSON object or JSONL line into a validated snapshot."""
    if isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload
    if not isinstance(data, dict):
        raise ValueError("conversation ticket snapshot must be a JSON object")
    return ConversationTicketSnapshot.model_validate(data)


def conversation_to_plain_text(snapshot: ConversationTicketSnapshot) -> str:
    """Readable transcript with sender labels; message order preserved."""
    lines: list[str] = []
    for message in snapshot.messages:
        lines.append(f"[{message.sender_type}] {message.text.strip()}")
    return "\n".join(lines)
