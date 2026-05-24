"""Safe truncated ticket text preview for HITL/operator visibility (no full transcript)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.privacy_review.redaction import (
    _CARD_PATTERN,
    _EMAIL_PATTERN,
    _IBAN_GENERIC_PATTERN,
    _IBAN_IR_PATTERN,
    _PHONE_GENERIC_PATTERN,
    _PHONE_IR_MOBILE_PATTERN,
    assert_redacted_export_safe,
    redact_pii_text,
)
from app.tickets.conversation_models import ConversationTicketSnapshot

TICKET_TEXT_PREVIEW_MAX_LENGTH = 400
_TRANSCRIPT_HEADER = "Conversation transcript:\n"
_VENDOR_SENDER_TYPES = frozenset({"seller"})
_FULL_TRANSCRIPT_MARKERS = (
    "conversation transcript:",
    "messages[",
    '"messages"',
)


def _truncate_preview(text: str, *, max_length: int = TICKET_TEXT_PREVIEW_MAX_LENGTH) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1].rstrip() + "…"


def _contains_unredacted_pii(text: str) -> bool:
    patterns = (
        _EMAIL_PATTERN,
        _IBAN_IR_PATTERN,
        _IBAN_GENERIC_PATTERN,
        _PHONE_IR_MOBILE_PATTERN,
        _PHONE_GENERIC_PATTERN,
        _CARD_PATTERN,
    )
    return any(pattern.search(text) for pattern in patterns)


def assert_ticket_text_preview_safe(
    preview: str,
    *,
    max_length: int = TICKET_TEXT_PREVIEW_MAX_LENGTH,
) -> None:
    """Fail closed if preview may expose full transcript or raw PII."""
    if not isinstance(preview, str):
        raise ValueError("ticket_text_preview must be a string")
    stripped = preview.strip()
    if not stripped:
        raise ValueError("ticket_text_preview must be non-empty when set")
    if len(stripped) > max_length:
        raise ValueError(f"ticket_text_preview exceeds max length {max_length}")
    lowered = stripped.lower()
    for marker in _FULL_TRANSCRIPT_MARKERS:
        if marker in lowered:
            raise ValueError("ticket_text_preview must not contain transcript markers")
    if stripped.count("\n") > 2:
        raise ValueError("ticket_text_preview must not contain multi-message transcript layout")
    if _contains_unredacted_pii(stripped):
        raise ValueError("ticket_text_preview contains unredacted PII-like patterns")
    assert_redacted_export_safe(stripped)


def _preview_source_from_snapshot(snapshot: ConversationTicketSnapshot) -> str | None:
    for message in reversed(snapshot.messages):
        if message.sender_type in _VENDOR_SENDER_TYPES:
            text = message.text.strip()
            if text:
                return text
    if snapshot.messages:
        fallback = snapshot.messages[-1].text.strip()
        return fallback or None
    return None


def _preview_source_from_user_input(user_input: str) -> str | None:
    text = user_input.strip()
    if not text:
        return None
    if text.startswith(_TRANSCRIPT_HEADER):
        body = text[len(_TRANSCRIPT_HEADER) :].strip()
        if not body or "seller:" in body.lower() or "support_agent:" in body.lower():
            return None
        return body.splitlines()[0].strip() if body else None
    return text


def build_ticket_text_preview(
    *,
    snapshot: ConversationTicketSnapshot | None = None,
    user_input: str | None = None,
    max_length: int = TICKET_TEXT_PREVIEW_MAX_LENGTH,
) -> str | None:
    """Build redacted, truncated preview text (never a full transcript)."""
    raw: str | None = None
    if snapshot is not None:
        raw = _preview_source_from_snapshot(snapshot)
    if not raw and user_input:
        raw = _preview_source_from_user_input(user_input)
    if not raw:
        return None

    redacted = redact_pii_text(raw).redacted_text.strip()
    if not redacted:
        return None
    truncated = _truncate_preview(redacted, max_length=max_length)
    assert_ticket_text_preview_safe(truncated, max_length=max_length)
    return truncated


def build_ticket_text_preview_from_snapshot(
    snapshot: ConversationTicketSnapshot,
    *,
    max_length: int = TICKET_TEXT_PREVIEW_MAX_LENGTH,
) -> str | None:
    return build_ticket_text_preview(snapshot=snapshot, max_length=max_length)


def build_ticket_text_preview_from_row(
    row: Mapping[str, Any],
    *,
    snapshot: ConversationTicketSnapshot | None = None,
    max_length: int = TICKET_TEXT_PREVIEW_MAX_LENGTH,
) -> str | None:
    """Use explicit snapshot when available; never read messages[] from export rows."""
    if snapshot is not None:
        return build_ticket_text_preview(snapshot=snapshot, max_length=max_length)
    user_input = row.get("user_input")
    if isinstance(user_input, str):
        return build_ticket_text_preview(user_input=user_input, max_length=max_length)
    return None


def attach_ticket_text_preview_to_row(
    row: dict[str, Any],
    *,
    snapshot: ConversationTicketSnapshot | None = None,
) -> dict[str, Any]:
    """Add ticket_text_preview to an export row when a safe preview can be built."""
    if row.get("ticket_text_preview") is not None:
        existing = row["ticket_text_preview"]
        if isinstance(existing, str) and existing.strip():
            assert_ticket_text_preview_safe(existing.strip())
        return row
    preview = build_ticket_text_preview_from_row(row, snapshot=snapshot)
    if preview is None:
        return row
    updated = dict(row)
    updated["ticket_text_preview"] = preview
    return updated
