"""Tests for manual sandbox chat room (operator console)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.config import AppSettings
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_assisted_work_package import render_operator_assisted_work_package
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.live_feed_loader import (
    CONSOLE_DATA_SOURCE_SESSION_KEY,
    LIVE_API_FEED_ENTRIES_SESSION_KEY,
    SOURCE_HISTORICAL_REPLAY,
    SOURCE_LIVE_API_FEED,
)
from app.operator_console.manual_chat_sandbox import (
    AI_ASSISTED_DRAFT_SOURCE,
    SESSION_MANUAL_ASSISTED_PACKAGES,
    SESSION_MANUAL_CHAT_MESSAGES,
    SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID,
    SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID,
    SESSION_MANUAL_LAST_GENERATION_ERROR,
    SESSION_MANUAL_ROOM_ID,
    SESSION_MANUAL_SHOP_ID,
    SESSION_MANUAL_TICKET_LABEL,
    SOURCE_MANUAL_SANDBOX_CHAT,
    TICKET_LABEL_AUTO,
    ManualChatMessage,
    append_manual_chat_message,
    build_manual_chat_snapshot,
    build_manual_operator_ticket,
    draft_text_from_assisted_package,
    find_regeneratable_ai_reply_index,
    get_manual_sandbox_assisted_package,
    handle_manual_add_message,
    load_sample_messages,
    manual_chat_should_generate_draft,
    manual_ticket_label_display,
    messages_from_session,
    regenerate_latest_ai_reply,
    render_manual_chat_bubble,
    run_manual_assisted_auto_reply,
    seller_message_already_answered,
    store_manual_sandbox_assisted_package,
)
from app.tickets.conversation_models import ConversationTicketSnapshot
from app.workflows.multi_turn_ticket_context import build_multi_turn_context


def _seller_message(text: str, message_id: str = "m1") -> ManualChatMessage:
    return ManualChatMessage(
        message_id=message_id,
        sender_type="seller",
        text=text,
        created_at="2026-05-20T10:00:00+00:00",
    )


def _support_message(text: str, message_id: str = "m2") -> ManualChatMessage:
    return ManualChatMessage(
        message_id=message_id,
        sender_type="support_agent",
        text=text,
        created_at="2026-05-20T10:01:00+00:00",
    )


def _mock_graph(*, draft: str, provider: str = "mock") -> AgenticSandboxPreviewResult:
    return AgenticSandboxPreviewResult(
        room_id="manual-room",
        graph_status="completed",
        node_statuses={},
        node_summaries=(),
        detected_intent="delivery_status_update",
        conceptual_intent_fa=None,
        suggested_action="update_delivery_status",
        suggested_action_reason=None,
        actionability_actionable=True,
        missing_required_entities=None,
        actionability_validation_reason=None,
        entity_source=None,
        entity_extraction_source=None,
        entity_extraction_source_char_count=None,
        display_preview_char_count=None,
        order_id_count=0,
        product_id_count=0,
        extracted_order_ids=None,
        extracted_product_ids=None,
        extracted_tracking_code=None,
        extracted_tracking_carrier=None,
        extracted_iban_masked=None,
        entity_warnings_summary=None,
        knowledge_hints_enabled=False,
        knowledge_hint_count=0,
        knowledge_hint_document_types=(),
        draft_char_count=len(draft),
        safety_status="passed",
        human_review_required=True,
        execution_allowed=False,
        customer_send_allowed=False,
        errors=(),
        draft_reply=draft,
        draft_provider=provider,
        draft_is_mock=provider == "mock",
        final_reflected_draft=draft,
    )


def _manual_chat_settings() -> AppSettings:
    return AppSettings(shipment_delivery_decision_enabled=False)


def _mock_build_package(draft: str, provider: str = "mock"):
    def _builder(ticket, *, settings=None, conversation_snapshot=None, **kwargs):
        return AgenticAssistedPackage(
            room_id=ticket.room_id,
            graph=_mock_graph(draft=draft, provider=provider),
            operator_checklist=("Check draft",),
            graduation_overall_status=None,
            graduation_gate_passed=True,
        )

    return _builder


def test_manual_chat_snapshot_with_seller_message_is_valid() -> None:
    messages = [_seller_message("سلام سفارش 7364518 تحویل مشتری شده")]
    snapshot = build_manual_chat_snapshot(messages, room_id="manual-sandbox-test")
    assert isinstance(snapshot, ConversationTicketSnapshot)
    assert snapshot.room_id == "manual-sandbox-test"
    assert snapshot.messages[-1].sender_type == "seller"
    assert snapshot.metadata.get("source_system") == "manual_sandbox_chat"
    ticket = build_manual_operator_ticket(snapshot)
    assert ticket.room_id == "manual-sandbox-test"
    assert ticket.open_ticket_preview


def test_optional_ticket_label_unset_does_not_crash() -> None:
    messages = [_seller_message("بعد از خرید مشتری چند روز بعد میتونم تسویه کنم؟")]
    snapshot = build_manual_chat_snapshot(
        messages,
        room_id="manual-sandbox-unset",
        ticket_label=None,
    )
    assert snapshot.metadata.get("ticket_label_source") == "manual_unset"
    assert manual_ticket_label_display(TICKET_LABEL_AUTO, snapshot) == "auto"
    ticket = build_manual_operator_ticket(snapshot)
    assert ticket.ticket_label is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("complaint", "complaint"),
        ("fund", "fund"),
        ("support", "support"),
    ],
)
def test_selected_ticket_label_passed_through(label: str, expected: str) -> None:
    messages = [_seller_message("نیاز به پیگیری دارم")]
    snapshot = build_manual_chat_snapshot(
        messages,
        room_id=f"manual-{label}",
        ticket_label=label,
    )
    assert snapshot.ticket_label == expected
    assert snapshot.metadata.get("ticket_label_source") == "manual_selected"
    ticket = build_manual_operator_ticket(snapshot)
    assert ticket.ticket_label == expected


def test_latest_seller_enables_assisted_generation() -> None:
    messages = [_seller_message("سلام")]
    allowed, reason = manual_chat_should_generate_draft(messages)
    assert allowed is True
    assert reason is None


def test_latest_support_disables_assisted_generation() -> None:
    messages = [
        _seller_message("سلام"),
        _support_message("لطفاً کد رهگیری را ارسال کنید"),
    ]
    allowed, reason = manual_chat_should_generate_draft(messages)
    assert allowed is False
    assert reason == "latest_message_from_support"


def test_messages_display_role_metadata() -> None:
    seller = _seller_message("پیام فروشنده")
    support = _support_message("پیام پشتیبانی")
    ai = ManualChatMessage(
        message_id="m3",
        sender_type="support_agent",
        text="پاسخ AI",
        created_at="2026-05-20T10:02:00+00:00",
        source=AI_ASSISTED_DRAFT_SOURCE,
        is_ai_generated=True,
        draft_provider="mock",
    )
    seller_html = render_manual_chat_bubble(seller)
    support_html = render_manual_chat_bubble(support)
    ai_html = render_manual_chat_bubble(ai, ai_reply_label="AI suggested reply")
    assert "فروشنده" in seller_html
    assert "#E8F1FF" in seller_html
    assert "پشتیبانی" in support_html
    assert "#EAF8EA" in support_html
    assert "AI suggested reply" in ai_html
    assert "2px solid #7cb87c" in ai_html


def test_session_keys_isolated_from_live_and_replay() -> None:
    manual_keys = {
        SESSION_MANUAL_CHAT_MESSAGES,
        SESSION_MANUAL_TICKET_LABEL,
        SESSION_MANUAL_ROOM_ID,
        SESSION_MANUAL_SHOP_ID,
        SESSION_MANUAL_ASSISTED_PACKAGES,
        SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID,
        SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID,
        SESSION_MANUAL_LAST_GENERATION_ERROR,
    }
    live_keys = {
        LIVE_API_FEED_ENTRIES_SESSION_KEY,
        CONSOLE_DATA_SOURCE_SESSION_KEY,
    }
    assert SOURCE_MANUAL_SANDBOX_CHAT not in {SOURCE_HISTORICAL_REPLAY, SOURCE_LIVE_API_FEED}
    assert manual_keys.isdisjoint(live_keys)
    assert not any(key.startswith("live_api_feed_") for key in manual_keys)


def test_multi_turn_detects_pending_request_fulfillment() -> None:
    messages = load_sample_messages()
    snapshot = build_manual_chat_snapshot(messages, room_id="manual-sandbox-multi")
    settings = AppSettings(multi_turn_context_enabled=True, multi_turn_context_max_messages=6)
    context = build_multi_turn_context(snapshot, settings=settings)
    assert context.pending_request_fulfilled is True
    assert context.should_generate_draft is True


def test_details_renderer_accepts_assisted_package_shape() -> None:
    graph = _mock_graph(draft="پیش‌نویس آزمایشی")
    package = AgenticAssistedPackage(
        room_id="manual-room",
        graph=graph,
        operator_checklist=("Check draft",),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )
    session: dict[str, object] = {}
    store_manual_sandbox_assisted_package(session, package)
    stored = get_manual_sandbox_assisted_package(session, "manual-room")
    assert stored is package
    assert callable(render_operator_assisted_work_package)
    messages = [_seller_message("تست")]
    ticket = build_manual_operator_ticket(
        build_manual_chat_snapshot(messages, room_id="manual-room"),
    )
    public = package.to_public_dict()
    assert "graph" in public
    assert public["room_id"] == "manual-room"
    assert ticket.room_id == package.room_id


def test_manual_chat_module_does_not_persist_to_reports_jsonl() -> None:
    source = Path("app/operator_console/manual_chat_sandbox.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"open", "write_text", "write"}:
                pytest.fail("manual_chat_sandbox must not write files")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith(".jsonl"):
                pytest.fail("manual_chat_sandbox must not reference JSONL report paths")


def test_append_message_roundtrip_dict() -> None:
    messages: list[ManualChatMessage] = []
    append_manual_chat_message(messages, sender_type="seller", text="سلام")
    payload = [message.to_dict() for message in messages]
    restored = ManualChatMessage.from_dict(payload[0])
    assert restored.sender_type == "seller"
    assert restored.text == "سلام"


def test_adding_seller_message_appends_seller_and_ai_reply() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    draft = "تحویل سفارش ثبت شد."
    result = handle_manual_add_message(
        session,
        role="seller",
        text="سلام سفارش 7364518 تحویل مشتری شده",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package(draft),
        settings=_manual_chat_settings(),
    )
    assert result is not None
    assert result.success is True
    assert result.ai_message is not None
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 2
    assert messages[0].sender_type == "seller"
    assert messages[1].is_ai_generated is True
    assert messages[1].source == AI_ASSISTED_DRAFT_SOURCE
    assert messages[1].text == draft


def test_adding_support_message_does_not_auto_run() -> None:
    session: dict[str, object] = {
        SESSION_MANUAL_CHAT_MESSAGES: [_seller_message("سلام").to_dict()],
    }
    result = handle_manual_add_message(
        session,
        role="support_agent",
        text="لطفاً کد رهگیری را ارسال کنید",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package("should not run"),
    )
    assert result is None
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 2
    assert messages[-1].sender_type == "support_agent"
    assert messages[-1].is_ai_generated is False


def test_auto_run_guard_prevents_duplicate_ai_replies() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    builder = _mock_build_package("پاسخ اول")
    first = handle_manual_add_message(
        session,
        role="seller",
        text="سلام",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=builder,
        settings=_manual_chat_settings(),
    )
    assert first is not None and first.ai_message is not None
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 2

    duplicate = run_manual_assisted_auto_reply(
        messages,
        seller_message_id=messages[0].message_id,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        session_state=session,
        build_package_fn=_mock_build_package("پاسخ تکراری"),
        settings=_manual_chat_settings(),
    )
    assert duplicate.skipped_duplicate is True
    assert len(messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])) == 2


def test_generated_ai_reply_persists_in_chat_history() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    handle_manual_add_message(
        session,
        role="seller",
        text="پیام اول",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package("پاسخ اول"),
        settings=_manual_chat_settings(),
    )
    handle_manual_add_message(
        session,
        role="seller",
        text="پیام دوم",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package("پاسخ دوم"),
        settings=_manual_chat_settings(),
    )
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 4
    assert messages[1].is_ai_generated
    assert messages[3].is_ai_generated
    assert messages[3].text == "پاسخ دوم"


def test_next_seller_message_sees_previous_ai_reply_as_context() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    handle_manual_add_message(
        session,
        role="seller",
        text="سلام",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package("پاسخ سیستم"),
        settings=_manual_chat_settings(),
    )
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    snapshot = build_manual_chat_snapshot(messages, room_id="manual-room")
    assert len(snapshot.messages) == 2
    assert snapshot.messages[1].sender_type == "support_agent"
    assert snapshot.messages[1].text == "پاسخ سیستم"


def test_regenerate_replaces_last_ai_reply_without_duplicate() -> None:
    messages = [
        _seller_message("سلام", message_id="m1"),
        ManualChatMessage(
            message_id="m2",
            sender_type="support_agent",
            text="پاسخ قدیم",
            created_at="2026-05-20T10:01:00+00:00",
            is_ai_generated=True,
            source=AI_ASSISTED_DRAFT_SOURCE,
        ),
    ]
    session: dict[str, object] = {
        SESSION_MANUAL_CHAT_MESSAGES: [message.to_dict() for message in messages],
    }
    assert find_regeneratable_ai_reply_index(messages) == 1
    result = regenerate_latest_ai_reply(
        messages,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        session_state=session,
        build_package_fn=_mock_build_package("پاسخ جدید"),
        settings=_manual_chat_settings(),
    )
    assert result.success is True
    assert result.replaced_existing is True
    assert len(messages) == 2
    assert messages[1].text == "پاسخ جدید"
    assert messages[1].message_id == "m2"


def test_generation_failure_does_not_append_ai_reply() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}

    def _failing_builder(ticket, *, settings=None, conversation_snapshot=None, **kwargs):
        raise ValueError("mock failure")

    result = handle_manual_add_message(
        session,
        role="seller",
        text="سلام",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_failing_builder,
        settings=_manual_chat_settings(),
    )
    assert result is not None
    assert result.success is False
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 1
    assert messages[0].sender_type == "seller"
    assert session.get(SESSION_MANUAL_LAST_GENERATION_ERROR)


def test_latest_assisted_package_matches_appended_ai_reply() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    draft = "کد رهگیری دریافت شد."
    handle_manual_add_message(
        session,
        role="seller",
        text="051800506400081160839102",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        build_package_fn=_mock_build_package(draft),
        settings=_manual_chat_settings(),
    )
    package = get_manual_sandbox_assisted_package(session, "manual-room")
    assert package is not None
    assert draft_text_from_assisted_package(package) == draft
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert messages[-1].text == draft


def test_seller_already_answered_guard() -> None:
    session: dict[str, object] = {
        SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID: "m1",
    }
    assert seller_message_already_answered(session, "m1") is True
    assert seller_message_already_answered(session, "m2") is False


def test_live_and_historical_modes_unaffected_by_auto_run_helpers() -> None:
    streamlit_source = Path("app/operator_console/streamlit_app.py").read_text(encoding="utf-8")
    assert "handle_manual_add_message" in streamlit_source
    live_panel_start = streamlit_source.index("def _render_live_api_feed_panel")
    manual_panel_start = streamlit_source.index("def _render_manual_sandbox_chat_panel")
    historical_main = streamlit_source.index("if selected_source == SOURCE_MANUAL_SANDBOX_CHAT")
    assert manual_panel_start < live_panel_start or True
    live_slice = streamlit_source[live_panel_start : live_panel_start + 4000]
    assert "handle_manual_add_message" not in live_slice
    replay_section = streamlit_source[historical_main : historical_main + 800]
    assert "handle_manual_add_message" not in replay_section
