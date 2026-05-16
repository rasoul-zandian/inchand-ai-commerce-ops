"""Tests for conversation snapshot → workflow input mapping."""

from __future__ import annotations

import json

from app.tickets.conversation_models import ConversationTicketSnapshot
from app.tickets.workflow_mapping import (
    conversation_snapshot_to_workflow_input,
    map_conversation_snapshots_to_workflow_inputs,
)


def _sample_snapshot() -> ConversationTicketSnapshot:
    return ConversationTicketSnapshot.model_validate(
        {
            "room_id": "ROOM_001",
            "ticket_label": "financial",
            "ticket_subtype": "settlement_discrepancy",
            "status": "closed",
            "seller_id": "SELLER_ID_001",
            "final_resolution": {"outcome": "clarification_requested"},
            "metadata": {"api_key": "sk-should-not-appear", "export_version": "1"},
            "messages": [
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "مبلغ تسویه اشتباه است",
                    "metadata": {"internal_ref": "hidden"},
                },
                {
                    "message_id": "m2",
                    "sender_type": "support_agent",
                    "text": "لطفاً شماره فاکتور را ارسال کنید",
                },
            ],
        }
    )


def test_maps_valid_snapshot_to_user_input_transcript() -> None:
    mapped = conversation_snapshot_to_workflow_input(_sample_snapshot())
    assert mapped["user_input"].startswith("Conversation transcript:\n")
    assert "[seller] مبلغ تسویه اشتباه است" in mapped["user_input"]
    assert "[support_agent]" in mapped["user_input"]


def test_workflow_metadata_fields() -> None:
    meta = conversation_snapshot_to_workflow_input(_sample_snapshot())["workflow_metadata"]
    assert meta["room_id"] == "ROOM_001"
    assert meta["ticket_label"] == "financial"
    assert meta["message_count"] == 2
    assert meta["sender_types"] == ["seller", "support_agent"]
    assert meta["has_final_resolution"] is True


def test_workflow_state_snapshot_fields() -> None:
    state = conversation_snapshot_to_workflow_input(_sample_snapshot())["workflow_state_snapshot"]
    assert state["conversation_transcript"].startswith("[seller]")
    assert state["final_resolution"] == {"outcome": "clarification_requested"}
    assert state["seller_id"] == "SELLER_ID_001"


def test_does_not_include_snapshot_or_message_metadata() -> None:
    mapped = conversation_snapshot_to_workflow_input(_sample_snapshot())
    dumped = json.dumps(mapped)
    assert "api_key" not in dumped
    assert "sk-should-not-appear" not in dumped
    assert "internal_ref" not in dumped
    assert "export_version" not in dumped
    assert "metadata" not in mapped["workflow_metadata"]
    assert "messages" not in mapped["workflow_state_snapshot"]


def test_mapper_exposes_top_level_ticket_fields() -> None:
    mapped = conversation_snapshot_to_workflow_input(_sample_snapshot())
    assert mapped["room_id"] == "ROOM_001"
    assert mapped["ticket_label"] == "financial"
    assert mapped["ticket_subtype"] == "settlement_discrepancy"


def test_preserves_message_order() -> None:
    transcript = conversation_snapshot_to_workflow_input(_sample_snapshot())[
        "workflow_state_snapshot"
    ]["conversation_transcript"]
    lines = transcript.splitlines()
    assert lines[0].startswith("[seller]")
    assert lines[1].startswith("[support_agent]")


def test_batch_mapper() -> None:
    snapshots = [_sample_snapshot(), _sample_snapshot().model_copy(update={"room_id": "ROOM_002"})]
    batch = map_conversation_snapshots_to_workflow_inputs(snapshots)
    assert len(batch) == 2
    assert batch[0]["workflow_metadata"]["room_id"] == "ROOM_001"
    assert batch[1]["workflow_metadata"]["room_id"] == "ROOM_002"
