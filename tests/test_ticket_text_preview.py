"""Tests for safe HITL ticket text preview."""

from __future__ import annotations

import json

import pytest
from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
)
from app.hitl.ticket_text_preview import (
    TICKET_TEXT_PREVIEW_MAX_LENGTH,
    assert_ticket_text_preview_safe,
    build_ticket_text_preview_from_snapshot,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot


def _snapshot_payload(*, text: str = "Need help with payout", room_id: str = "ROOM_P1") -> str:
    return json.dumps(
        {
            "room_id": room_id,
            "ticket_label": "support",
            "messages": [
                {
                    "message_id": "m1",
                    "sender_type": "support_agent",
                    "text": "How can we help?",
                },
                {
                    "message_id": "m2",
                    "sender_type": "seller",
                    "text": text,
                },
            ],
        },
        ensure_ascii=False,
    )


def test_preview_prefers_latest_seller_message() -> None:
    snapshot = parse_conversation_ticket_snapshot(_snapshot_payload(text="Seller issue details"))
    preview = build_ticket_text_preview_from_snapshot(snapshot)
    assert preview is not None
    assert "Seller issue details" in preview


def test_preview_is_truncated() -> None:
    long_text = "word " * 200
    snapshot = parse_conversation_ticket_snapshot(_snapshot_payload(text=long_text))
    preview = build_ticket_text_preview_from_snapshot(snapshot)
    assert preview is not None
    assert len(preview) <= TICKET_TEXT_PREVIEW_MAX_LENGTH


def test_preview_rejects_unredacted_phone() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_ticket_text_preview_safe("Call me at 09121234567")


def test_hitl_payload_accepts_safe_preview() -> None:
    snapshot = parse_conversation_ticket_snapshot(_snapshot_payload())
    preview = build_ticket_text_preview_from_snapshot(snapshot)
    row = {
        "room_id": "ROOM_P1",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "review_priority": "LOW",
        "assigned_department": "support",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_priority": "medium",
        "ai_assist_escalation_recommended": False,
        "ai_assist_duplicate_possible": False,
        "ai_assist_suggested_action": "monitor",
        "ai_assist_confidence_band": "high",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "ticket_text_preview": preview,
    }
    payload = build_hitl_read_only_payload_from_replay_row(row)
    assert_hitl_payload_ready(payload)
    assert "messages" not in payload
    assert payload["ticket_text_preview"] == preview


def test_hitl_payload_rejects_messages_array() -> None:
    row = {
        "room_id": "ROOM_P1",
        "ticket_label": "support",
        "messages": [{"text": "secret"}],
        "ai_assist_shadow_only": True,
        "ai_assist_human_review_required": True,
        "retrieval_activated": False,
    }
    with pytest.raises(ValueError, match="forbidden"):
        build_hitl_read_only_payload_from_replay_row(row)
