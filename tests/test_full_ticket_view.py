"""Tests for operator-console full conversation view (internal only)."""

from __future__ import annotations

import json

from app.operator_console.full_ticket_view import (
    build_full_ticket_conversation,
    render_full_ticket_conversation_html,
    render_full_ticket_conversation_markdown,
    sanitize_full_ticket_message,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot


def _snapshot_json(messages: list[dict[str, str]], *, room_id: str = "ROOM_FULL") -> str:
    return json.dumps(
        {
            "room_id": room_id,
            "ticket_label": "fund",
            "status": "open",
            "messages": messages,
        },
        ensure_ascii=False,
    )


def test_long_messages_not_truncated() -> None:
    long_body = "سلام " + ("متن طولانی " * 80) + "SKU-998877"
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "seller", "text": long_body},
            ],
        ),
    )
    conversation = build_full_ticket_conversation(snapshot)
    assert len(conversation.messages) == 1
    assert len(conversation.messages[0].text) > 400
    assert "SKU-998877" in conversation.messages[0].text
    assert "…" not in conversation.messages[0].text


def test_message_ordering_preserved() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "seller", "text": "اول"},
                {"message_id": "m2", "sender_type": "support_agent", "text": "پاسخ"},
                {"message_id": "m3", "sender_type": "finance_agent", "text": "مالی"},
            ],
        ),
    )
    conversation = build_full_ticket_conversation(snapshot)
    roles = [message.role_label for message in conversation.messages]
    assert roles == ["vendor", "support", "finance"]
    markdown = render_full_ticket_conversation_markdown(conversation)
    assert markdown.index("vendor:") < markdown.index("support:") < markdown.index("finance:")


def test_pii_redacted_in_full_view() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "تماس 09123456789",
                },
            ],
        ),
    )
    conversation = build_full_ticket_conversation(snapshot)
    assert "[PHONE_NUMBER]" in conversation.messages[0].text
    assert "09123456789" not in conversation.messages[0].text


def test_internal_system_messages_excluded() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "system", "text": "hidden routing"},
                {"message_id": "m2", "sender_type": "unknown", "text": "unknown actor"},
                {"message_id": "m3", "sender_type": "seller", "text": "visible vendor"},
            ],
        ),
    )
    conversation = build_full_ticket_conversation(snapshot)
    assert len(conversation.messages) == 1
    assert conversation.messages[0].role_label == "vendor"


def test_multiline_message_preserved() -> None:
    body = "خط اول\nخط دوم"
    sanitized = sanitize_full_ticket_message(body)
    assert sanitized is not None
    assert "\n" in sanitized


def test_mixed_persian_english_html_readable() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "سلام سفارش ORDER-12345 و 9876543210",
                },
            ],
        ),
    )
    conversation = build_full_ticket_conversation(snapshot)
    html_block = render_full_ticket_conversation_html(conversation)
    assert "vendor:" in html_block
    assert 'dir="ltr"' in html_block
    assert "ORDER-12345" in html_block
    assert "unicode-bidi:plaintext" in html_block
