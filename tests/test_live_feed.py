"""Minimal sanity tests for live vendor ticket feed adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.live_feed.ticket_feed_adapter import (
    build_operator_payload_from_live_ticket,
    fetch_new_vendor_tickets_since,
    normalize_live_ticket,
)
from app.live_feed.ticket_models import LiveFeedCheckpoint
from app.live_feed.ticket_polling import load_checkpoint, save_checkpoint


def _snapshot_line(room_id: str = "ROOM_LIVE_1") -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": "support",
        "messages": [
            {
                "message_id": "m1",
                "sender_type": "seller",
                "text": "Need help with payout",
                "timestamp": "2026-05-19T10:00:00+00:00",
            },
        ],
        "created_at": "2026-05-19T09:00:00+00:00",
    }
    return json.dumps(payload)


def test_normalize_live_ticket() -> None:
    ticket = normalize_live_ticket(_snapshot_line())
    assert ticket.room_id == "ROOM_LIVE_1"
    assert ticket.ticket_label == "support"
    assert "seller" in ticket.user_input.lower()
    assert ticket.updated_at is not None


def test_checkpoint_load_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint = LiveFeedCheckpoint(
        last_seen_updated_at=datetime(2026, 5, 19, tzinfo=UTC).isoformat(),
        seen_room_ids=["A", "B"],
        last_poll_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC).isoformat(),
    )
    save_checkpoint(checkpoint, path)
    loaded = load_checkpoint(path)
    assert loaded.seen_room_ids == ["A", "B"]
    assert loaded.last_seen_updated_at == checkpoint.last_seen_updated_at


def test_fetch_new_vendor_tickets_since(tmp_path: Path) -> None:
    feed = tmp_path / "live.jsonl"
    feed.write_text(_snapshot_line("R1") + "\n" + _snapshot_line("R2") + "\n", encoding="utf-8")
    checkpoint = LiveFeedCheckpoint(seen_room_ids=["R1"])
    new = fetch_new_vendor_tickets_since(feed, checkpoint, max_batch=10)
    assert len(new) == 1
    assert new[0].room_id == "R2"


def test_build_operator_payload_from_live_ticket() -> None:
    ticket = normalize_live_ticket(_snapshot_line())
    fake_row = {
        "room_id": "ROOM_LIVE_1",
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
        "retrieval_gate_decision": "allow",
        "retrieval_result_count": 2,
        "retrieval_activated": False,
        "retrieval_sandbox_only": True,
    }
    with (
        patch(
            "app.live_feed.ticket_feed_adapter.export_shadow_replay_row_for_snapshot",
            return_value=fake_row,
        ),
        patch(
            "app.live_feed.ticket_feed_adapter.export_ai_assist_shadow_replay_row_for_snapshot",
            return_value=fake_row,
        ),
        patch("app.live_feed.ticket_feed_adapter.configure_mock_workflow_runtime"),
    ):
        payload = build_operator_payload_from_live_ticket(ticket)
    assert payload["room_id"] == "ROOM_LIVE_1"
    assert payload["ai_assist_suggested_action"] == "monitor"
    assert payload["retrieval_result_count"] == 2
    assert "user_input" not in payload
