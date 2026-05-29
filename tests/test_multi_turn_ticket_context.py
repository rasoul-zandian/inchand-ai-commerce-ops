"""Tests for operational multi-turn ticket context foundation."""

from __future__ import annotations

import json

from app.agentic_sandbox.final_draft_reflection import (
    FinalDraftReflectionContext,
    apply_final_draft_reflection_review,
    run_deterministic_reflection_checks,
)
from app.config import AppSettings
from app.evals.actionability_validation import validate_actionability
from app.live_feed.ticket_models import LiveVendorTicket
from app.operator_console.agentic_sandbox_preview import sanitize_agentic_preview_result
from app.operator_console.live_feed_loader import classify_live_feed_dashboard_eligibility
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.multi_turn_ticket_context import (
    PendingRequestType,
    apply_multi_turn_context_to_actionability,
    apply_multi_turn_metadata_to_actionability,
    build_multi_turn_context,
    collect_meaningful_messages,
    is_closed_ticket_status,
    multi_turn_context_metadata_row,
    pending_fulfillment_ack_for_type,
)


def _message(
    message_id: str,
    sender_type: str,
    text: str,
) -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        sender_type=sender_type,
        text=text,
    )


def _snapshot(
    messages: list[ConversationMessage],
    *,
    status: str = "open",
) -> ConversationTicketSnapshot:
    return ConversationTicketSnapshot(
        room_id="room-1",
        ticket_label="support",
        status=status,
        messages=messages,
    )


def test_detect_tracking_request_from_extended_admin_phrases() -> None:
    assert (
        build_multi_turn_context(
            _snapshot([_message("1", "support_agent", "لطفاً tracking code را بفرستید")]),
            settings=AppSettings(multi_turn_context_enabled=True),
        ).pending_request_type
        == PendingRequestType.REQUESTED_TRACKING_CODE
    )


def test_seller_long_numeric_code_fulfills_tracking_without_explicit_words() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "لطفاً کد رهگیری را ارسال کنید"),
            _message("2", "seller", "051800506400081160839102"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_type == PendingRequestType.REQUESTED_TRACKING_CODE
    assert ctx.pending_request_fulfilled is True


def test_seller_numeric_only_without_prior_tracking_request_not_fulfilled() -> None:
    snapshot = _snapshot([_message("1", "seller", "051800506400081160839102")])
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_fulfilled is False
    assert ctx.pending_request_type is None


def test_optional_postal_tracking_request_fulfilled_without_code() -> None:
    snapshot = _snapshot(
        [
            _message(
                "1",
                "support_agent",
                "لطفاً روش ارسال و کد رهگیری پستی را در صورت وجود ارسال کنید.",
            ),
            _message("2", "seller", "با پیک ارسال کردم"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_type == PendingRequestType.REQUESTED_TRACKING_CODE
    assert ctx.pending_request_fulfilled is True
    row = multi_turn_context_metadata_row(ctx)
    assert row.get("multi_turn_tracking_optional") is True
    ack = pending_fulfillment_ack_for_type(
        ctx.pending_request_type.value,
        tracking_optional=True,
    )
    assert ack == "درخواست شما ثبت و در دست بررسی قرار گرفت."


def test_tracking_request_fulfilled_after_admin_ask() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "لطفاً کد رهگیری را ارسال کنید"),
            _message("2", "seller", "051800506400081160839102"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_type == PendingRequestType.REQUESTED_TRACKING_CODE
    assert ctx.pending_request_fulfilled is True
    assert ctx.should_generate_draft is True
    assert pending_fulfillment_ack_for_type(ctx.pending_request_type.value) is not None


def test_order_id_request_fulfilled() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "شماره سفارش لطفاً"),
            _message("2", "seller", "سفارش 7367917 را لغو کنید"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_type == PendingRequestType.REQUESTED_ORDER_ID
    assert ctx.pending_request_fulfilled is True
    assert "7367917" in ctx.extracted_order_ids_all


def test_product_id_from_earlier_turn_not_missing() -> None:
    snapshot = _snapshot(
        [
            _message("1", "seller", "شناسه کالا 12345678"),
            _message("2", "support_agent", "لطفاً منتظر بمانید"),
            _message("3", "seller", "وضعیت چی شد؟"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert "12345678" in ctx.extracted_product_ids_all
    validation = validate_actionability(
        suggested_action="check_product_approval",
        order_ids=(),
        product_ids=(),
        seller_text=ctx.latest_seller_message or "",
    )
    assert "product_id" in validation.missing_required_entities
    overlay = apply_multi_turn_context_to_actionability(ctx, validation)
    assert overlay.actionable is True
    assert "product_id" not in overlay.missing_required_entities


def test_latest_support_message_skips_draft() -> None:
    snapshot = _snapshot(
        [
            _message("1", "seller", "سلام"),
            _message("2", "support_agent", "در حال بررسی هستیم"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.should_generate_draft is False
    assert ctx.should_skip_reason == "latest_message_from_support"


def test_closed_ticket_skips_draft() -> None:
    snapshot = _snapshot(
        [_message("1", "seller", "سلام")],
        status="closed",
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.should_generate_draft is False
    assert ctx.should_skip_reason == "closed_ticket"


def test_closed_ticket_skips_even_when_pending_request_fulfilled() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "لطفاً کد رهگیری را ارسال کنید"),
            _message("2", "seller", "051800506400081160839102"),
        ],
        status="closed",
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.pending_request_fulfilled is True
    assert ctx.should_generate_draft is False
    assert ctx.should_skip_reason == "closed_ticket"


def test_persian_closed_status_skips_draft() -> None:
    assert is_closed_ticket_status("بسته شده")
    snapshot = _snapshot(
        [_message("1", "seller", "وضعیت سفارش چیست؟")],
        status="بسته شده",
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.should_generate_draft is False
    assert ctx.should_skip_reason == "closed_ticket"


def test_open_ticket_with_latest_seller_allows_draft() -> None:
    snapshot = _snapshot(
        [_message("1", "seller", "وضعیت سفارش چیست؟")],
        status="open",
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    assert ctx.should_generate_draft is True
    assert ctx.should_skip_reason is None


def test_multi_turn_disabled_preserves_generate_flag() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "در حال بررسی"),
            _message("2", "seller", "سلام"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=False))
    assert ctx.should_generate_draft is True
    assert ctx.multi_turn_context_enabled is False


def test_max_message_window_respected() -> None:
    messages = [
        _message(str(index), "seller" if index % 2 == 0 else "support_agent", f"msg {index}")
        for index in range(12)
    ]
    snapshot = _snapshot(messages)
    ctx = build_multi_turn_context(
        snapshot,
        settings=AppSettings(multi_turn_context_enabled=True, multi_turn_context_max_messages=6),
    )
    assert len(ctx.recent_turns) <= 6


def test_reflection_catches_repeated_ask_after_fulfilled_pending() -> None:
    context = FinalDraftReflectionContext(
        seller_text="051800506400081160839102",
        pending_request_type=PendingRequestType.REQUESTED_TRACKING_CODE.value,
        pending_request_fulfilled=True,
        context_tracking_codes=("051800506400081160839102",),
    )
    findings = run_deterministic_reflection_checks(
        "لطفاً کد رهگیری را ارسال کنید.",
        context,
    )
    issue_types = {item.issue_type.value for item in findings}
    assert "repeated_identifier_request" in issue_types


def test_preview_metadata_has_no_transcript() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "شماره سفارش لطفاً"),
            _message("2", "seller", "7367917"),
        ],
    )
    ctx = build_multi_turn_context(snapshot, settings=AppSettings(multi_turn_context_enabled=True))
    meta = multi_turn_context_metadata_row(ctx)
    public = json.dumps(
        sanitize_agentic_preview_result(
            {
                "room_id": "room-1",
                "draft_reply": "test",
                "safety_status": "passed",
                "human_review_required": True,
                "execution_allowed": False,
                "customer_send_allowed": False,
                "errors": [],
                "multi_turn_context_metadata": meta,
            },
            knowledge_hints_enabled=False,
        ).to_public_dict(),
        ensure_ascii=False,
    )
    assert ': "7367917"' not in public
    assert "INC-7367917" in public
    assert meta.get("inchand_order_id_candidate") == "INC-7367917"
    assert "messages" not in public
    assert "transcript" not in public


def test_live_feed_eligibility_when_multi_turn_enabled() -> None:
    snapshot = _snapshot(
        [
            _message("1", "support_agent", "کد رهگیری؟"),
            _message("2", "seller", "1234567890123"),
        ],
    )
    ticket = LiveVendorTicket(
        room_id="room-1",
        created_at=None,
        updated_at=None,
        ticket_label="support",
        user_input="seller preview",
        assigned_department=None,
        review_priority=None,
        snapshot=snapshot,
    )
    eligible, reason = classify_live_feed_dashboard_eligibility(
        ticket,
        settings=AppSettings(multi_turn_context_enabled=True),
    )
    assert eligible is True
    assert reason is None


def test_metadata_overlay_fulfills_missing_order_id() -> None:
    meta = {
        "multi_turn_context_enabled": True,
        "multi_turn_has_order_ids": True,
        "multi_turn_pending_request_fulfilled": False,
    }
    validation = validate_actionability(
        suggested_action="check_order_status",
        order_ids=(),
        product_ids=(),
    )
    overlay = apply_multi_turn_metadata_to_actionability(meta, validation)
    assert overlay.actionable is True


def test_integration_reflection_rewrite_for_fulfilled_order() -> None:
    final, result = apply_final_draft_reflection_review(
        "لطفاً شماره سفارش را ارسال کنید.",
        seller_text="7367917",
        suggested_action="human_followup",
        order_ids=("7367917",),
        pending_request_type=PendingRequestType.REQUESTED_ORDER_ID.value,
        pending_request_fulfilled=True,
        context_order_ids=("7367917",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "شماره سفارش" not in final or "دریافت شد" in final


def test_meaningful_messages_skip_system_only() -> None:
    snapshot = _snapshot(
        [
            _message("1", "system", "auto notice"),
            _message("2", "seller", "سلام"),
        ],
    )
    meaningful = collect_meaningful_messages(snapshot.messages, max_messages=6)
    assert len(meaningful) == 1
    assert meaningful[0].sender_type == "seller"
