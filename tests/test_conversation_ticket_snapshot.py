"""Tests for conversation ticket snapshot contract."""

from __future__ import annotations

import json

import pytest
from app.tickets.conversation_models import (
    ConversationMessage,
    ConversationTicketSnapshot,
    conversation_to_plain_text,
    parse_conversation_ticket_snapshot,
)
from pydantic import ValidationError

_EXPORT_DOC = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "docs"
    / "data_governance"
    / "real_ticket_export_format.md"
)


def _valid_payload() -> dict:
    return {
        "room_id": "ROOM_001",
        "ticket_label": "financial",
        "ticket_subtype": "settlement_discrepancy",
        "seller_id": "SELLER_ID_001",
        "messages": [
            {
                "message_id": "msg-1",
                "sender_type": "seller",
                "text": "مبلغ تسویه اشتباه است",
            },
            {
                "message_id": "msg-2",
                "sender_type": "support_agent",
                "text": "لطفاً شماره فاکتور را ارسال کنید",
            },
        ],
    }


def test_valid_snapshot_parses() -> None:
    snapshot = parse_conversation_ticket_snapshot(_valid_payload())
    assert snapshot.room_id == "ROOM_001"
    assert snapshot.ticket_label == "financial"
    assert len(snapshot.messages) == 2
    assert snapshot.messages[0].sender_type == "seller"


def test_jsonl_line_parse() -> None:
    line = json.dumps(_valid_payload(), ensure_ascii=False)
    snapshot = parse_conversation_ticket_snapshot(line)
    assert snapshot.seller_id == "SELLER_ID_001"


def test_rejects_empty_messages() -> None:
    payload = _valid_payload()
    payload["messages"] = []
    with pytest.raises(ValidationError, match="at least one message"):
        ConversationTicketSnapshot.model_validate(payload)


def test_rejects_unsupported_sender_type() -> None:
    with pytest.raises(ValidationError, match="sender_type"):
        ConversationMessage(
            message_id="m1",
            sender_type="customer",
            text="سلام",
        )


def test_rejects_empty_message_text() -> None:
    with pytest.raises(ValidationError, match="text"):
        ConversationMessage(
            message_id="m1",
            sender_type="seller",
            text="   ",
        )


def test_conversation_to_plain_text_preserves_order_and_roles() -> None:
    snapshot = ConversationTicketSnapshot.model_validate(_valid_payload())
    transcript = conversation_to_plain_text(snapshot)
    lines = transcript.splitlines()
    assert lines[0].startswith("[seller]")
    assert lines[1].startswith("[support_agent]")
    assert "فاکتور" in lines[1]


def test_export_format_doc_mentions_jsonl_and_placeholders() -> None:
    text = _EXPORT_DOC.read_text(encoding="utf-8")
    assert "JSONL" in text
    assert "SELLER_ID_001" in text
    assert "local-only mapping table" in text.lower() or "local-only mapping" in text
    assert "OPENAI_API_KEY" not in text
    assert "postgresql://" not in text


def test_export_format_doc_lists_excluded_fields() -> None:
    text = _EXPORT_DOC.read_text(encoding="utf-8")
    assert "phone" in text.lower() or "Phone" in text
    assert "IBAN" in text
    assert "attachment" in text.lower()
