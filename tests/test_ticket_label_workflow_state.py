"""Tests for ticket_label / room_id propagation into workflow state."""

from __future__ import annotations

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.common import normalize_request
from app.nodes.vendor_ticket import build_review_queue_metadata
from app.review_queue import build_review_queue_item
from app.tickets import (
    apply_ticket_context_to_state,
    conversation_snapshot_to_workflow_input,
)
from app.tickets.conversation_models import ConversationTicketSnapshot

from tests.test_vendor_ticket_workflow import make_base_state


def _snapshot(*, label: str = "financial") -> ConversationTicketSnapshot:
    return ConversationTicketSnapshot.model_validate(
        {
            "room_id": "ROOM_WIRE_001",
            "ticket_label": label,
            "ticket_subtype": "settlement_discrepancy",
            "messages": [
                {"message_id": "m1", "sender_type": "seller", "text": "سلام"},
            ],
        }
    )


def test_mapper_includes_ticket_fields_at_top_level_and_snapshot() -> None:
    mapped = conversation_snapshot_to_workflow_input(_snapshot(label="complaint"))
    assert mapped["room_id"] == "ROOM_WIRE_001"
    assert mapped["ticket_label"] == "complaint"
    assert mapped["ticket_subtype"] == "settlement_discrepancy"
    assert mapped["workflow_state_snapshot"]["ticket_label"] == "complaint"


def test_apply_ticket_context_from_nested_snapshot() -> None:
    state = make_base_state()
    state["workflow_state_snapshot"] = {
        "room_id": "ROOM_NESTED",
        "ticket_label": "مالی",
        "ticket_subtype": "billing",
    }
    updated = apply_ticket_context_to_state(state)
    assert updated["room_id"] == "ROOM_NESTED"
    assert updated["ticket_label"] == "مالی"
    assert updated["ticket_subtype"] == "billing"


def test_normalize_request_promotes_ticket_label() -> None:
    state = make_base_state()
    state["workflow_state_snapshot"] = {"ticket_label": "شکایت"}
    normalized = normalize_request(state)
    assert normalized["ticket_label"] == "شکایت"


def test_review_metadata_department_route_uses_persian_mali() -> None:
    state = make_base_state()
    state["ticket_label"] = "مالی"
    state["route_label"] = "general_vendor_support"
    state["human_approval_required"] = True
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "finance"


def test_review_metadata_complaint_label() -> None:
    state = make_base_state()
    state["ticket_label"] = "شکایت"
    state["human_approval_required"] = True
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "complaint"


def test_route_label_fallback_when_ticket_label_missing() -> None:
    state = make_base_state()
    state["route_label"] = "billing_review"
    state["human_approval_required"] = True
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "finance"


def test_review_queue_item_metadata_includes_ticket_context() -> None:
    state = make_base_state()
    state["room_id"] = "ROOM_META"
    state["ticket_label"] = "support"
    state["ticket_subtype"] = "general"
    state["human_approval_required"] = True
    item = build_review_queue_item(state)
    assert item.metadata["room_id"] == "ROOM_META"
    assert item.metadata["ticket_label"] == "support"
    assert item.metadata["ticket_subtype"] == "general"


def test_run_vendor_ticket_demo_with_ticket_label() -> None:
    state = run_vendor_ticket_demo(
        "سلام",
        ticket_id="t-wire-label",
        room_id="ROOM_DEMO",
        ticket_label="مالی",
        ticket_subtype="settlement",
    )
    assert state["ticket_label"] == "مالی"
    assert state["room_id"] == "ROOM_DEMO"
    meta = build_review_queue_metadata(state)
    assert meta["department_route"]["assigned_department"] == "finance"
