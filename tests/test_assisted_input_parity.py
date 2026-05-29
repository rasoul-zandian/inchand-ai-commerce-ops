"""Tests for assisted input parity between manual sandbox and historical replay."""

from __future__ import annotations

from dataclasses import replace

from app.config import AppSettings
from app.operator_console.assisted_input_consistency import (
    build_assisted_input_snapshot_from_historical,
    build_assisted_input_snapshot_from_manual,
    build_manual_ticket_for_comparison,
    compare_assisted_input_snapshots,
    text_fingerprint,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_assisted_graph_input_from_operator_ticket,
    build_conversation_snapshot_from_manual_messages,
    build_operator_ticket_from_manual_chat,
    is_ai_generated_conversation_message,
    manual_messages_to_conversation_messages,
    should_use_multi_turn_conversation_snapshot,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.manual_chat_sandbox import (
    ManualChatMessage,
    append_ai_support_reply,
    append_manual_chat_message,
)
from app.workflows.multi_turn_ticket_context import (
    build_multi_turn_context,
    is_closed_conversation_snapshot,
)

_SELLER_TEXT = "سلام سفارش 7364518 تحویل مشتری شده لطفا نهایی کنید"


def _historical_ticket() -> OperatorTicket:
    return OperatorTicket(
        room_id="7743",
        ticket_label="complaint",
        route_label="billing_review",
        shop_id="shop-1",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview="preview",
        open_ticket_preview="open",
        original_vendor_issue_preview=_SELLER_TEXT[:200],
        latest_vendor_message=_SELLER_TEXT[:200],
        recent_context_preview=None,
        full_first_vendor_message_text=_SELLER_TEXT,
    )


def test_same_text_manual_and_historical_response_target_match_first_turn() -> None:
    settings = AppSettings(multi_turn_context_enabled=True)
    historical = _historical_ticket()
    manual_ticket, manual_snapshot = build_manual_ticket_for_comparison(
        _SELLER_TEXT,
        room_id="7743",
        ticket_label="complaint",
        shop_id="shop-1",
    )
    hist_bundle = build_assisted_graph_input_from_operator_ticket(
        historical,
        conversation_snapshot=None,
        source_mode="historical_replay",
        settings=settings,
    )
    manual_bundle = build_assisted_graph_input_from_operator_ticket(
        manual_ticket,
        conversation_snapshot=manual_snapshot,
        source_mode="manual_sandbox_chat",
        settings=settings,
    )
    assert hist_bundle.multi_turn_active is False
    assert manual_bundle.multi_turn_active is False
    assert text_fingerprint(hist_bundle.response_target_seller_text) == text_fingerprint(
        manual_bundle.response_target_seller_text
    )


def test_manual_chat_sets_original_vendor_issue_preview() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text=_SELLER_TEXT)
    ticket, _snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="manual-room",
        ticket_label="complaint",
    )
    assert ticket.original_vendor_issue_preview
    assert _SELLER_TEXT.startswith(ticket.original_vendor_issue_preview[:50])


def test_manual_chat_sets_full_first_vendor_message_text() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text=_SELLER_TEXT)
    ticket, _snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="manual-room",
    )
    assert ticket.full_first_vendor_message_text == _SELLER_TEXT


def test_manual_chat_selected_ticket_label_passed() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    ticket, snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="manual-room",
        ticket_label="fund",
    )
    assert ticket.ticket_label == "fund"
    assert snapshot.metadata.get("ticket_label_source") == "manual_selected"


def test_manual_chat_unset_ticket_label_records_manual_unset() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    ticket, snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="manual-room",
        ticket_label=None,
    )
    assert ticket.ticket_label is None
    assert snapshot.metadata.get("ticket_label_source") == "manual_unset"


def test_manual_single_seller_skips_multi_turn_snapshot_for_graph() -> None:
    settings = AppSettings(multi_turn_context_enabled=True)
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text=_SELLER_TEXT)
    ticket, snapshot = build_operator_ticket_from_manual_chat(messages, room_id="r1")
    assert (
        should_use_multi_turn_conversation_snapshot(
            snapshot,
            settings=settings,
            source_mode="manual_sandbox_chat",
        )
        is False
    )


def test_ai_support_reply_not_used_for_entity_extraction() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    append_ai_support_reply(
        messages,
        "لطفاً کد رهگیری را ارسال کنید",
        draft_provider="mock",
    )
    append_manual_chat_message(messages, sender_type="seller", text="051800506400081160839102")
    ticket, snapshot = build_operator_ticket_from_manual_chat(messages, room_id="r1")
    settings = AppSettings(multi_turn_context_enabled=True)
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=snapshot,
        source_mode="manual_sandbox_chat",
        settings=settings,
    )
    assert bundle.multi_turn_active is True
    assert "051800506400081160839102" in bundle.entity_extraction_text
    assert "لطفاً کد رهگیری" not in bundle.entity_extraction_text


def test_ai_generated_message_metadata_on_conversion() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    append_ai_support_reply(messages, "پاسخ AI", draft_provider="mock")
    conv = manual_messages_to_conversation_messages(messages)
    assert is_ai_generated_conversation_message(conv[1]) is True


def test_comparator_detects_ticket_label_mismatch() -> None:
    settings = AppSettings()
    historical = _historical_ticket()
    manual_ticket, manual_snapshot = build_manual_ticket_for_comparison(
        _SELLER_TEXT,
        room_id="7743",
        ticket_label=None,
    )
    hist_row = build_assisted_input_snapshot_from_historical(historical, settings=settings)
    manual_row = build_assisted_input_snapshot_from_manual(
        manual_ticket,
        conversation_snapshot=manual_snapshot,
        settings=settings,
    )
    comparison = compare_assisted_input_snapshots(hist_row, manual_row)
    label_row = next(row for row in comparison.fields if row.field_name == "ticket_label")
    assert label_row.match is False


def test_comparator_detects_missing_full_first_vendor_on_historical_without_full() -> None:
    settings = AppSettings()
    historical = _historical_ticket()
    historical = OperatorTicket(
        room_id=historical.room_id,
        ticket_label=historical.ticket_label,
        route_label=historical.route_label,
        assigned_department=historical.assigned_department,
        review_priority=historical.review_priority,
        suggested_action=historical.suggested_action,
        suggested_priority=historical.suggested_priority,
        escalation_recommended=historical.escalation_recommended,
        duplicate_possible=historical.duplicate_possible,
        confidence_band=historical.confidence_band,
        retrieval_gate_decision=historical.retrieval_gate_decision,
        retrieval_result_count=historical.retrieval_result_count,
        ticket_text_preview=historical.ticket_text_preview,
        open_ticket_preview=historical.open_ticket_preview,
        original_vendor_issue_preview=historical.original_vendor_issue_preview,
        latest_vendor_message=historical.latest_vendor_message,
        recent_context_preview=historical.recent_context_preview,
        full_first_vendor_message_text=None,
        shop_id=historical.shop_id,
    )
    manual_ticket, manual_snapshot = build_manual_ticket_for_comparison(
        _SELLER_TEXT,
        room_id="7743",
        ticket_label="complaint",
    )
    hist_row = build_assisted_input_snapshot_from_historical(historical, settings=settings)
    manual_row = build_assisted_input_snapshot_from_manual(
        manual_ticket,
        conversation_snapshot=manual_snapshot,
        settings=settings,
    )
    comparison = compare_assisted_input_snapshots(hist_row, manual_row)
    fp_row = next(
        row
        for row in comparison.fields
        if row.field_name == "full_first_vendor_message_text_fingerprint"
    )
    assert fp_row.match is False


def test_pending_request_ignores_ai_support_reply() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    append_ai_support_reply(messages, "لطفاً کد رهگیری را ارسال کنید", draft_provider="mock")
    append_manual_chat_message(messages, sender_type="seller", text="051800506400081160839102")
    snapshot = build_conversation_snapshot_from_manual_messages(messages, room_id="r1")
    settings = AppSettings(multi_turn_context_enabled=True)
    context = build_multi_turn_context(snapshot, settings=settings)
    assert context.pending_request_fulfilled is False or context.pending_request_type is None


def test_closed_manual_ticket_forces_graph_snapshot_for_gating() -> None:
    settings = AppSettings(multi_turn_context_enabled=True)
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text="وضعیت سفارش چیست؟",
            created_at="2026-05-20T12:00:00Z",
        ),
    ]
    ticket, snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="closed-room",
        status="closed",
    )
    assert is_closed_conversation_snapshot(snapshot)
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=snapshot,
        source_mode="manual_sandbox_chat",
        settings=settings,
    )
    assert bundle.conversation_snapshot is snapshot
    assert bundle.safe_metadata.get("multi_turn_should_generate_draft") is False
    assert bundle.safe_metadata.get("multi_turn_skip_reason") == "closed_ticket"


def test_graph_intent_matches_for_same_text_and_label_mock_provider() -> None:
    from app.operator_console.agentic_assisted_mode import build_agentic_assisted_package

    settings = AppSettings(
        operator_agentic_assisted_mode_enabled=True,
        operator_agentic_assisted_require_graduation_ready=False,
        operator_agentic_sandbox_provider="mock",
        operator_agentic_assisted_provider="mock",
        operator_agentic_assisted_knowledge_hints_enabled=False,
        operator_agentic_sandbox_knowledge_hints_enabled=False,
        knowledge_hints_enabled=False,
        multi_turn_context_enabled=True,
    )
    historical = replace(_historical_ticket(), route_label=None)
    manual_ticket, manual_snapshot = build_manual_ticket_for_comparison(
        _SELLER_TEXT,
        room_id="7743",
        ticket_label="complaint",
        shop_id="shop-1",
    )
    hist_pkg = build_agentic_assisted_package(
        historical,
        settings=settings,
        conversation_snapshot=None,
        source_mode="historical_replay",
    )
    manual_pkg = build_agentic_assisted_package(
        manual_ticket,
        settings=settings,
        conversation_snapshot=manual_snapshot,
        source_mode="manual_sandbox_chat",
    )
    assert hist_pkg.graph.detected_intent == manual_pkg.graph.detected_intent
    assert hist_pkg.graph.suggested_action == manual_pkg.graph.suggested_action
