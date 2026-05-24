"""Open-ticket snapshot for operator review (current vendor turn; no post-resolution leakage)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii, _truncate_preview
from app.privacy_review.redaction import assert_redacted_export_safe, redact_pii_text
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot

OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS = 600
OPEN_TICKET_ORIGINAL_MAX_CHARS = 200
# Internal extraction ceiling only (not UI preview); avoids unbounded transcript storage.
FULL_FIRST_VENDOR_MESSAGE_MAX_CHARS = 4096
OPEN_TICKET_LATEST_MAX_CHARS = 200
OPEN_TICKET_CONTEXT_MAX_CHARS = 200
OPEN_TICKET_RECENT_MESSAGE_LIMIT = 3

_VENDOR_SENDER_TYPES = frozenset({"seller"})
_INTERNAL_SENDER_TYPES = frozenset({"system", "unknown"})
_CONTEXT_SENDER_LABELS = {
    "seller": "vendor",
    "support_agent": "support",
    "finance_agent": "finance",
}


@dataclass(frozen=True)
class OpenTicketSnapshot:
    """Redacted open-ticket view (no messages array; operational slice only)."""

    original_vendor_issue_preview: str | None
    latest_vendor_message: str | None
    recent_context_preview: str | None
    open_ticket_preview: str | None


def _redact_and_clean(text: str) -> str:
    return redact_pii_text(text).redacted_text.strip()


def _first_vendor_index(messages: list[ConversationMessage]) -> int | None:
    for index, message in enumerate(messages):
        if message.sender_type in _VENDOR_SENDER_TYPES:
            return index
    return None


def _latest_vendor_index(messages: list[ConversationMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].sender_type in _VENDOR_SENDER_TYPES:
            return index
    return None


def extract_full_first_vendor_message(snapshot: ConversationTicketSnapshot) -> str | None:
    """First seller/vendor message only — full redacted text for internal entity extraction."""
    index = _first_vendor_index(snapshot.messages)
    if index is None:
        return None
    text = snapshot.messages[index].text.strip()
    if not text:
        return None
    redacted = _redact_and_clean(text)
    if not redacted or _contains_unredacted_pii(redacted):
        return None
    if len(redacted) > FULL_FIRST_VENDOR_MESSAGE_MAX_CHARS:
        return _truncate_preview(redacted, max_length=FULL_FIRST_VENDOR_MESSAGE_MAX_CHARS)
    return redacted


def extract_original_vendor_issue(snapshot: ConversationTicketSnapshot) -> str | None:
    """First seller/vendor message in the room (truncated safe preview for UI/prompts)."""
    full = extract_full_first_vendor_message(snapshot)
    if not full:
        return None
    return _truncate_preview(full, max_length=OPEN_TICKET_ORIGINAL_MAX_CHARS)


def extract_latest_vendor_message(snapshot: ConversationTicketSnapshot) -> str | None:
    """Latest seller/vendor message only (excludes later support/future turns)."""
    index = _latest_vendor_index(snapshot.messages)
    if index is None:
        return None
    text = snapshot.messages[index].text.strip()
    if not text:
        return None
    redacted = _redact_and_clean(text)
    if not redacted or _contains_unredacted_pii(redacted):
        return None
    return _truncate_preview(redacted, max_length=OPEN_TICKET_LATEST_MAX_CHARS)


def extract_recent_context(
    snapshot: ConversationTicketSnapshot,
    *,
    max_prior_messages: int = OPEN_TICKET_RECENT_MESSAGE_LIMIT,
) -> str | None:
    """Up to N prior messages before latest vendor turn (no internal; no post-vendor support)."""
    index = _latest_vendor_index(snapshot.messages)
    if index is None or index == 0:
        return None

    prior = snapshot.messages[max(0, index - max_prior_messages) : index]
    parts: list[str] = []
    for message in prior:
        if message.sender_type in _INTERNAL_SENDER_TYPES:
            continue
        label = _CONTEXT_SENDER_LABELS.get(message.sender_type, message.sender_type)
        text = _redact_and_clean(message.text)
        if not text or _contains_unredacted_pii(text):
            continue
        parts.append(f"{label}: {text}")

    if not parts:
        return None
    combined = " | ".join(parts)
    return _truncate_preview(combined, max_length=OPEN_TICKET_CONTEXT_MAX_CHARS)


def _enforce_combined_budget(
    original: str | None,
    latest: str | None,
    context: str | None,
    *,
    max_total_chars: int = OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS,
) -> tuple[str | None, str | None, str | None]:
    """Shrink context, then original, then latest until combined length fits budget."""
    o = (original or "").strip() or None
    l_msg = (latest or "").strip() or None
    c = (context or "").strip() or None

    def _total() -> int:
        return sum(len(x) for x in (o, l_msg, c) if x)

    while _total() > max_total_chars:
        if c and len(c) > 50:
            c = _truncate_preview(c, max_length=max(50, len(c) - 30))
        elif o and len(o) > 50:
            o = _truncate_preview(o, max_length=max(50, len(o) - 30))
        elif l_msg and len(l_msg) > 50:
            l_msg = _truncate_preview(l_msg, max_length=max(50, len(l_msg) - 30))
        else:
            break

    return (o, l_msg, c)


def _build_open_preview(
    original: str | None,
    latest: str | None,
    context: str | None,
    *,
    max_chars: int = OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS,
) -> str | None:
    parts: list[str] = []
    if original:
        parts.append(f"Original: {original}")
    if latest:
        parts.append(f"Latest: {latest}")
    if context:
        parts.append(f"Recent: {context}")
    if not parts:
        return None
    return _truncate_preview(" — ".join(parts), max_length=max_chars)


def assert_open_ticket_snapshot_field_safe(value: str, *, field_name: str) -> None:
    """Fail closed on transcript leakage or raw PII in snapshot text fields."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty when set")
    lowered = stripped.lower()
    if "conversation transcript" in lowered or '"messages"' in lowered:
        raise ValueError(f"{field_name} must not reference full transcript")
    if _contains_unredacted_pii(stripped):
        raise ValueError(f"{field_name} contains unredacted PII-like patterns")
    assert_redacted_export_safe(stripped)


def assert_open_ticket_snapshot_safe(snapshot: Mapping[str, str | None]) -> None:
    """Validate open ticket snapshot fields and combined size."""
    body_fields = (
        "original_vendor_issue_preview",
        "latest_vendor_message",
        "recent_context_preview",
    )
    total = 0
    for field in body_fields:
        value = snapshot.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string when present")
        assert_open_ticket_snapshot_field_safe(value, field_name=field)
        total += len(value)

    preview = snapshot.get("open_ticket_preview")
    if preview is not None:
        if not isinstance(preview, str):
            raise ValueError("open_ticket_preview must be a string when present")
        assert_open_ticket_snapshot_field_safe(preview, field_name="open_ticket_preview")
        if len(preview) > OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS:
            raise ValueError("open_ticket_preview exceeds max length")

    if total > OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS:
        raise ValueError("open ticket snapshot body fields exceed combined max length")


def build_open_ticket_snapshot(
    snapshot: ConversationTicketSnapshot,
) -> OpenTicketSnapshot:
    """Build redacted open-ticket snapshot (original issue + latest vendor + recent context)."""
    original = extract_original_vendor_issue(snapshot)
    latest = extract_latest_vendor_message(snapshot)
    context = extract_recent_context(snapshot)
    original, latest, context = _enforce_combined_budget(original, latest, context)
    open_preview = _build_open_preview(original, latest, context)

    fields = {
        "original_vendor_issue_preview": original,
        "latest_vendor_message": latest,
        "recent_context_preview": context,
        "open_ticket_preview": open_preview,
    }
    if any(fields.values()):
        assert_open_ticket_snapshot_safe(fields)
    return OpenTicketSnapshot(
        original_vendor_issue_preview=original,
        latest_vendor_message=latest,
        recent_context_preview=context,
        open_ticket_preview=open_preview,
    )


def open_ticket_snapshot_to_payload(snapshot: OpenTicketSnapshot) -> dict[str, str | None]:
    return {
        "original_vendor_issue_preview": snapshot.original_vendor_issue_preview,
        "latest_vendor_message": snapshot.latest_vendor_message,
        "recent_context_preview": snapshot.recent_context_preview,
        "open_ticket_preview": snapshot.open_ticket_preview,
    }


def attach_open_ticket_snapshot_to_row(
    row: dict[str, Any],
    *,
    snapshot: ConversationTicketSnapshot | None = None,
) -> dict[str, Any]:
    """Attach open ticket snapshot fields to an export row when snapshot is available."""
    if snapshot is None:
        return row
    if row.get("open_ticket_preview") is not None:
        assert_open_ticket_snapshot_safe(
            {
                "original_vendor_issue_preview": row.get("original_vendor_issue_preview"),
                "latest_vendor_message": row.get("latest_vendor_message"),
                "recent_context_preview": row.get("recent_context_preview"),
                "open_ticket_preview": row.get("open_ticket_preview"),
            },
        )
        return row
    built = build_open_ticket_snapshot(snapshot)
    if not any(
        (
            built.original_vendor_issue_preview,
            built.latest_vendor_message,
            built.recent_context_preview,
            built.open_ticket_preview,
        ),
    ):
        return row
    updated = dict(row)
    updated.update(open_ticket_snapshot_to_payload(built))
    return updated
