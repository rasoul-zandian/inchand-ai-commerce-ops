from __future__ import annotations

from app.agentic_sandbox.final_draft_reflection import (
    apply_final_draft_reflection_review,
    reflection_metadata_row,
)
from app.config import get_settings
from app.live_feed.ticket_feed_adapter import normalize_live_ticket
from app.live_shadow.live_first_turn_shadow_intake import operator_ticket_from_live_ticket
from app.operator_console.assisted_ticket_input_builder import (
    build_assisted_graph_input_from_operator_ticket,
    build_operator_ticket_from_manual_chat,
    parity_debug_row_with_settings,
)
from app.operator_console.manual_chat_models import ManualChatMessage


def _live_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "room_id": "r-1",
        "ticket_label": "support",
        "status": "open",
        "created_at": "2026-05-20T09:00:00+00:00",
        "updated_at": "2026-05-20T09:01:00+00:00",
        "messages": [
            {
                "message_id": "m1",
                "sender_type": "seller",
                "text": "می‌خواهم اسم فروشگاه را تغییر بدهم",
                "created_at": "2026-05-20T09:00:00+00:00",
            },
        ],
        "shop_id": "shop-1",
        "seller_id": "seller-2",
        "shop_name": "demo-shop",
        "shop_identity_available": True,
    }
    row.update(overrides)
    return row


def test_operator_ticket_preserves_shop_identity_metadata() -> None:
    ticket = normalize_live_ticket(_live_row())
    operator = operator_ticket_from_live_ticket(ticket)
    assert operator.shop_id == "shop-1"
    assert operator.seller_id == "seller-2"
    assert operator.shop_name == "demo-shop"
    assert operator.shop_identity_available is True


def test_assisted_graph_input_carries_runtime_shop_identity_available_true() -> None:
    ticket = normalize_live_ticket(_live_row())
    operator = operator_ticket_from_live_ticket(ticket)
    bundle = build_assisted_graph_input_from_operator_ticket(
        operator,
        conversation_snapshot=ticket.snapshot,
        source_mode="live_api_feed",
    )
    debug = parity_debug_row_with_settings(bundle, settings=get_settings())
    assert debug["runtime_shop_identity_available"] is True
    assert debug["runtime_shop_id_present"] is True


def test_final_draft_reflection_metadata_receives_runtime_identity_true() -> None:
    _final, result = apply_final_draft_reflection_review(
        draft="لطفاً شناسه فروشگاه خود را ارسال کنید.",
        seller_text="می‌خواهم اسم فروشگاه را تغییر بدهم",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        shop_id="shop-1",
    )
    row = reflection_metadata_row(result)
    assert row["reflection_runtime_shop_identity_available"] is True
    assert row["reflection_runtime_shop_id_present"] is True


def test_manual_sandbox_with_shop_id_triggers_rewrite() -> None:
    final, _ = apply_final_draft_reflection_review(
        draft="لطفاً شناسه فروشگاه خود را برای تغییر نام ارسال کنید.",
        seller_text="می‌خواهم اسم فروشگاه را تغییر بدهم",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        shop_id="manual-sandbox-shop",
    )
    assert final == "درخواست شما ثبت شد و در دست بررسی قرار گرفت."


def test_manual_sandbox_without_shop_id_reports_runtime_false() -> None:
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text="می‌خواهم اسم فروشگاه را تغییر بدهم",
            created_at="2026-05-20T09:00:00+00:00",
        ),
    ]
    ticket, snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id="manual-room",
        ticket_label="support",
        shop_id=None,
    )
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=snapshot,
        source_mode="manual_sandbox_chat",
    )
    debug = parity_debug_row_with_settings(bundle, settings=get_settings())
    assert debug["runtime_shop_identity_available"] is False
    assert debug["runtime_shop_id_present"] is False


def test_reflection_public_metadata_does_not_include_raw_shop_id() -> None:
    _final, result = apply_final_draft_reflection_review(
        draft="لطفاً شناسه فروشگاه خود را ارسال کنید.",
        seller_text="می‌خواهم اسم فروشگاه را تغییر بدهم",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        shop_id="12345678",
    )
    row = reflection_metadata_row(result)
    serialized = str(row)
    assert "12345678" not in serialized


def test_shop_name_change_scenario_passes_when_identity_available() -> None:
    final, result = apply_final_draft_reflection_review(
        draft="لطفاً شناسه فروشگاه خود را برای تغییر نام ارسال کنید.",
        seller_text="می‌خواهم اسم فروشگاه را به شالیزار تغییر بدهم",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        shop_id="shop-42",
    )
    assert final == "درخواست شما ثبت شد و در دست بررسی قرار گرفت."
    assert result.rewrite_applied is True
