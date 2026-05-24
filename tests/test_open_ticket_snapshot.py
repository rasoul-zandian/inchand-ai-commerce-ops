"""Tests for open ticket snapshot (operational vendor-turn slice)."""

from __future__ import annotations

import json

from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
)
from app.live_feed.open_ticket_snapshot import (
    OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS,
    build_open_ticket_snapshot,
    extract_latest_vendor_message,
    extract_original_vendor_issue,
    extract_recent_context,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot


def _snapshot_json(
    messages: list[dict[str, str]],
    *,
    room_id: str = "ROOM_OPEN",
) -> str:
    return json.dumps(
        {
            "room_id": room_id,
            "ticket_label": "support",
            "status": "open",
            "messages": messages,
        },
        ensure_ascii=False,
    )


def test_extract_original_vendor_issue_first_seller_only() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "support_agent", "text": "Hello"},
                {"message_id": "m2", "sender_type": "seller", "text": "First real vendor issue"},
                {"message_id": "m3", "sender_type": "seller", "text": "Follow-up vendor line"},
            ],
        ),
    )
    original = extract_original_vendor_issue(snapshot)
    assert original is not None
    assert "First real vendor issue" in original
    assert "Follow-up vendor line" not in original


def test_extract_latest_vendor_message() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "seller", "text": "First vendor ask"},
                {"message_id": "m2", "sender_type": "support_agent", "text": "We are checking"},
                {"message_id": "m3", "sender_type": "seller", "text": "Latest vendor update"},
                {
                    "message_id": "m4",
                    "sender_type": "support_agent",
                    "text": "Resolved for you",
                },
            ],
        ),
    )
    latest = extract_latest_vendor_message(snapshot)
    assert latest is not None
    assert "Latest vendor update" in latest
    assert "Resolved for you" not in latest


def test_future_support_leakage_blocked_in_snapshot() -> None:
    built = build_open_ticket_snapshot(
        parse_conversation_ticket_snapshot(
            _snapshot_json(
                [
                    {"message_id": "m1", "sender_type": "seller", "text": "Need payout help"},
                    {"message_id": "m2", "sender_type": "support_agent", "text": "Future reply"},
                ],
            ),
        ),
    )
    assert built.latest_vendor_message is not None
    assert "Future reply" not in (built.open_ticket_preview or "")
    assert "Future reply" not in (built.recent_context_preview or "")
    assert "Future reply" not in (built.original_vendor_issue_preview or "")


def test_recent_context_excludes_future_support_and_includes_prior_support() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "seller", "text": "Original ask"},
                {"message_id": "m2", "sender_type": "support_agent", "text": "Prior support line"},
                {"message_id": "m3", "sender_type": "seller", "text": "Latest vendor"},
                {"message_id": "m4", "sender_type": "support_agent", "text": "After vendor hidden"},
            ],
        ),
    )
    ctx = extract_recent_context(snapshot)
    assert ctx is not None
    assert "Prior support line" in ctx
    assert "After vendor hidden" not in ctx


def test_internal_messages_excluded_from_context() -> None:
    context = extract_recent_context(
        parse_conversation_ticket_snapshot(
            _snapshot_json(
                [
                    {"message_id": "m1", "sender_type": "system", "text": "internal note"},
                    {"message_id": "m2", "sender_type": "support_agent", "text": "Prior support"},
                    {"message_id": "m3", "sender_type": "seller", "text": "Vendor follow up"},
                ],
            ),
        ),
    )
    assert context is not None
    assert "internal" not in context.lower()
    assert "Prior support" in context


def test_truncation_respects_total_budget() -> None:
    long_vendor = "vendor " * 200
    long_original = "original " * 200
    long_ctx = "ctxword " * 200
    snapshot = parse_conversation_ticket_snapshot(
        _snapshot_json(
            [
                {"message_id": "m1", "sender_type": "seller", "text": long_original},
                {"message_id": "m2", "sender_type": "support_agent", "text": long_ctx},
                {"message_id": "m3", "sender_type": "seller", "text": long_vendor},
            ],
        ),
    )
    built = build_open_ticket_snapshot(snapshot)
    total = sum(
        len(part or "")
        for part in (
            built.original_vendor_issue_preview,
            built.latest_vendor_message,
            built.recent_context_preview,
        )
    )
    assert total <= OPEN_TICKET_SNAPSHOT_MAX_TOTAL_CHARS


def test_pii_redacted_in_original_issue() -> None:
    built = build_open_ticket_snapshot(
        parse_conversation_ticket_snapshot(
            _snapshot_json(
                [
                    {
                        "message_id": "m1",
                        "sender_type": "seller",
                        "text": "Payout issue call 09123456789 thanks",
                    },
                ],
            ),
        ),
    )
    assert built.original_vendor_issue_preview is not None
    assert "09123456789" not in built.original_vendor_issue_preview


def test_hitl_payload_with_open_snapshot_is_safe() -> None:
    built = build_open_ticket_snapshot(
        parse_conversation_ticket_snapshot(
            _snapshot_json(
                [
                    {"message_id": "m1", "sender_type": "support_agent", "text": "Hello"},
                    {"message_id": "m2", "sender_type": "seller", "text": "Vendor question"},
                ],
            ),
        ),
    )
    row = {
        "room_id": "ROOM_OPEN",
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
        "original_vendor_issue_preview": built.original_vendor_issue_preview,
        "latest_vendor_message": built.latest_vendor_message,
        "recent_context_preview": built.recent_context_preview,
        "open_ticket_preview": built.open_ticket_preview,
    }
    payload = build_hitl_read_only_payload_from_replay_row(row)
    assert_hitl_payload_ready(payload)
    assert "messages" not in payload
