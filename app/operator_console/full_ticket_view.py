"""Internal operator-console full conversation view (redacted; no truncation)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.hitl.ticket_text_preview import _contains_unredacted_pii
from app.operator_console.display_text import clean_redaction_placeholders_for_display
from app.privacy_review.redaction import assert_redacted_export_safe, redact_pii_text
from app.tickets.conversation_models import ConversationTicketSnapshot

_INTERNAL_SENDER_TYPES = frozenset({"system", "unknown"})
_ROLE_LABELS = {
    "seller": "vendor",
    "support_agent": "support",
    "finance_agent": "finance",
}

_FORBIDDEN_MESSAGE_MARKERS = (
    "openai_api_key",
    "sk-",
    "begin private key",
    "postgresql://",
)


@dataclass(frozen=True)
class FullConversationMessage:
    """One visible thread line for operator full view."""

    role_label: str
    text: str
    message_index: int


@dataclass(frozen=True)
class FullTicketConversation:
    """Ordered redacted conversation for one room (operator console only)."""

    room_id: str
    messages: tuple[FullConversationMessage, ...]


def _role_label_for_sender(sender_type: str) -> str | None:
    normalized = sender_type.strip().lower()
    if normalized in _INTERNAL_SENDER_TYPES:
        return None
    return _ROLE_LABELS.get(normalized, normalized)


def sanitize_full_ticket_message(text: str) -> str | None:
    """Redact PII and preserve multiline message bodies (no length truncation)."""
    if not text or not text.strip():
        return None
    redacted = redact_pii_text(text).redacted_text
    cleaned = redacted.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    for marker in _FORBIDDEN_MESSAGE_MARKERS:
        if marker in lowered:
            return None
    if _contains_unredacted_pii(cleaned):
        return None
    assert_redacted_export_safe(cleaned)
    return cleaned


def build_full_ticket_conversation(
    snapshot: ConversationTicketSnapshot,
) -> FullTicketConversation:
    """Build ordered full thread from snapshot (vendor/support/finance only)."""
    visible: list[FullConversationMessage] = []
    for index, message in enumerate(snapshot.messages):
        role = _role_label_for_sender(message.sender_type)
        if role is None:
            continue
        body = sanitize_full_ticket_message(message.text)
        if body is None:
            continue
        visible.append(
            FullConversationMessage(
                role_label=role,
                text=body,
                message_index=index,
            ),
        )
    return FullTicketConversation(room_id=snapshot.room_id, messages=tuple(visible))


def render_full_ticket_conversation_markdown(
    conversation: FullTicketConversation,
) -> str:
    """Plain-text thread for tests and non-HTML consumers."""
    if not conversation.messages:
        return "_No visible messages in this ticket._"
    lines = [f"{message.role_label}: {message.text}" for message in conversation.messages]
    return "\n\n".join(lines)


def _wrap_ltr_tokens_for_rtl(text: str) -> str:
    """Isolate common Latin/number runs so they stay readable inside RTL blocks."""
    pattern = re.compile(
        r"([A-Za-z][A-Za-z0-9_\-./]*[A-Za-z0-9]|[A-Za-z]{2,}|\d{4,})",
    )

    def _isolate(match: re.Match[str]) -> str:
        token = match.group(0)
        escaped = html.escape(token, quote=False)
        return (
            f'<span dir="ltr" style="unicode-bidi:isolate;display:inline-block;">{escaped}</span>'
        )

    escaped = html.escape(text, quote=False)
    return pattern.sub(_isolate, escaped)


def render_full_ticket_conversation_html(conversation: FullTicketConversation) -> str:
    """HTML thread with RTL-friendly mixed Persian/Latin rendering."""
    if not conversation.messages:
        return '<p style="color:#64748b;">No visible messages (internal/system lines excluded).</p>'
    blocks: list[str] = []
    for message in conversation.messages:
        body_html = _wrap_ltr_tokens_for_rtl(
            clean_redaction_placeholders_for_display(message.text),
        )
        role = html.escape(message.role_label, quote=False)
        blocks.append(
            '<div class="operator-full-msg" style="margin-bottom:1rem;">'
            f'<div dir="ltr" lang="en" style="font-weight:600;margin-bottom:0.25rem;">'
            f"{role}:</div>"
            '<div dir="rtl" style="text-align:right;unicode-bidi:plaintext;'
            "white-space:pre-wrap;line-height:1.6;padding:0.65rem 0.75rem;"
            "background:rgba(232,244,253,0.95);border-radius:0.5rem;"
            'border-right:4px solid #1c83e1;">'
            f"{body_html}</div></div>",
        )
    return '<div class="operator-full-thread">' + "".join(blocks) + "</div>"
