"""Tests for operator-console first-vendor-only listing filter."""

from __future__ import annotations

from datetime import UTC, datetime

from app.operator_console.console_models import OperatorTicket
from app.operator_console.first_vendor_filter import (
    FirstVendorFilterStats,
    apply_operator_first_vendor_filter,
    filter_first_vendor_tickets,
    first_meaningful_sender_type,
    is_first_vendor_ticket,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot


def _message(sender_type: str, *, message_id: str = "m1") -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        sender_type=sender_type,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        text="body",
    )


def _snapshot(*senders: str, room_id: str = "ROOM_A") -> ConversationTicketSnapshot:
    messages = [_message(sender, message_id=f"m{i}") for i, sender in enumerate(senders)]
    return ConversationTicketSnapshot(
        room_id=room_id,
        ticket_label="support",
        messages=messages,
    )


def _ticket(room_id: str) -> OperatorTicket:
    return OperatorTicket(
        room_id=room_id,
        ticket_label="support",
        route_label=None,
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=None,
        latest_vendor_message=None,
        recent_context_preview=None,
    )


def test_seller_first_included() -> None:
    snap = _snapshot("seller", "support_agent")
    assert is_first_vendor_ticket(snap)
    assert first_meaningful_sender_type(snap.messages) == "seller"


def test_support_first_excluded() -> None:
    snap = _snapshot("support_agent", "seller")
    assert not is_first_vendor_ticket(snap)
    assert first_meaningful_sender_type(snap.messages) == "support_agent"


def test_finance_first_excluded() -> None:
    snap = _snapshot("finance_agent", "seller")
    assert not is_first_vendor_ticket(snap)


def test_system_then_seller_included() -> None:
    snap = _snapshot("system", "seller", "support_agent")
    assert is_first_vendor_ticket(snap)


def test_unknown_then_seller_included() -> None:
    snap = _snapshot("unknown", "seller")
    assert is_first_vendor_ticket(snap)


def test_vendor_sender_included() -> None:
    """Raw vendor label (pre-canonical export) counts as seller-initiated."""
    messages = [{"sender_type": "vendor"}, {"sender_type": "support_agent"}]
    assert first_meaningful_sender_type(messages) == "vendor"

    class _Snap:
        messages = [
            type("M", (), {"sender_type": "vendor"})(),
            type("M", (), {"sender_type": "support_agent"})(),
        ]

    assert is_first_vendor_ticket(_Snap())  # type: ignore[arg-type]


def test_filter_first_vendor_tickets_by_snapshot_index() -> None:
    index = {
        "ROOM_SELLER": _snapshot("seller", room_id="ROOM_SELLER"),
        "ROOM_SUPPORT": _snapshot("support_agent", "seller", room_id="ROOM_SUPPORT"),
    }
    tickets = [_ticket("ROOM_SELLER"), _ticket("ROOM_SUPPORT"), _ticket("ROOM_MISSING")]
    filtered = filter_first_vendor_tickets(tickets, snapshot_index=index)
    assert [t.room_id for t in filtered] == ["ROOM_SELLER"]


def test_apply_filter_disabled_returns_all() -> None:
    tickets = [_ticket("A"), _ticket("B")]
    result, stats = apply_operator_first_vendor_filter(
        tickets,
        snapshot_index={},
        enabled=False,
    )
    assert result == tickets
    assert stats == FirstVendorFilterStats(
        total_loaded=2,
        tickets_shown=2,
        filter_active=False,
    )


def test_sidebar_counts_when_filter_active() -> None:
    index = {
        "A": _snapshot("seller", room_id="A"),
        "B": _snapshot("support_agent", room_id="B"),
        "C": _snapshot("seller", room_id="C"),
    }
    tickets = [_ticket("A"), _ticket("B"), _ticket("C")]
    result, stats = apply_operator_first_vendor_filter(
        tickets,
        snapshot_index=index,
        enabled=True,
    )
    assert stats.total_loaded == 3
    assert stats.tickets_shown == 2
    assert stats.filter_active is True
    assert len(result) == 2
    assert {t.room_id for t in result} == {"A", "C"}


def test_only_internal_messages_excluded() -> None:
    snap = _snapshot("system", "unknown")
    assert not is_first_vendor_ticket(snap)
    assert first_meaningful_sender_type(snap.messages) is None
