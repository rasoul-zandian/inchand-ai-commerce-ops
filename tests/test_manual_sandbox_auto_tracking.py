"""Tests for manual sandbox auto Iran Post tracking verification (Step 230)."""

from __future__ import annotations

import json
from typing import Any

from app.config import AppSettings
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.manual_chat_models import (
    AI_ASSISTED_DRAFT_SOURCE,
    IRAN_POST_TRACKING_SOURCE,
    ManualChatMessage,
)
from app.operator_console.manual_chat_sandbox import (
    SESSION_MANUAL_ASSISTED_PACKAGES,
    SESSION_MANUAL_CHAT_MESSAGES,
    append_manual_chat_message,
    handle_manual_add_message,
    messages_from_session,
    run_manual_assisted_auto_reply,
)
from app.operator_console.manual_sandbox_auto_tracking import (
    build_tracking_verification_chat_reply,
    get_tracking_result_for_message,
    should_run_manual_sandbox_auto_tracking,
    try_manual_sandbox_auto_tracking_verify,
)
from app.tools.tracking.iran_post_tracking import IranPostTrackingResult, parse_iran_post_response

_TRACKING_24 = "051800506400081160839102"
_ORDER_7 = "7367917"


def _auto_settings() -> AppSettings:
    return AppSettings(
        manual_sandbox_auto_tracking_verify_enabled=True,
        iran_post_tracking_enabled=True,
        iran_post_tracking_token="test-token",
    )


def _mock_graph(*, draft: str = "پیش‌نویس عمومی") -> AgenticSandboxPreviewResult:
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
        draft_provider="mock",
        draft_is_mock=True,
        final_reflected_draft=draft,
    )


def _mock_build_package(draft: str = "پیش‌نویس عمومی"):
    def _builder(ticket, *, settings=None, conversation_snapshot=None, **kwargs):
        return AgenticAssistedPackage(
            room_id=ticket.room_id,
            graph=_mock_graph(draft=draft),
            operator_checklist=("Check draft",),
            graduation_overall_status=None,
            graduation_gate_passed=True,
        )

    return _builder


def _verified_response() -> dict[str, Any]:
    return {
        "Status": {"Code": "0", "Description": "OK"},
        "Parameters": {
            "AcceptanceDateTime": "2024-01-01",
            "Destination": "Tehran",
            "Source": "Isfahan",
            "ReceiverName": "PRIVATE",
            "SenderName": "PRIVATE",
            "PostPackageStatusDetail": [
                {
                    "DateTime": "2024-01-02",
                    "ExtraInfo": "تحویل به واحد پست",
                    "Province": "تهران",
                },
            ],
        },
    }


def _mock_verify_ok(_code: str) -> IranPostTrackingResult:
    return parse_iran_post_response(_verified_response(), _TRACKING_24)


def _mock_verify_invalid(_code: str) -> IranPostTrackingResult:
    return parse_iran_post_response(
        {"Status": {"Code": "error", "Description": "not found"}, "Parameters": {}},
        _TRACKING_24,
    )


def _mock_verify_timeout(_code: str) -> IranPostTrackingResult:
    return IranPostTrackingResult(
        tracking_code=_TRACKING_24,
        is_plausible_code=True,
        verified=False,
        error_type="timeout",
        error_message="timed out",
    )


def test_seller_plausible_code_triggers_auto_verification() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    result = handle_manual_add_message(
        session,
        role="seller",
        text=_TRACKING_24,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package("نباید در چت بیاید"),
        verify_tracking_fn=_mock_verify_ok,
    )
    assert result is not None
    assert result.success is True
    assert result.tracking_verification_attempted is True
    assert result.used_tracking_reply is True
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert len(messages) == 2
    assert messages[1].source == IRAN_POST_TRACKING_SOURCE
    assert messages[1].tracking_verification_used is True
    assert get_tracking_result_for_message(session, messages[0].message_id) is not None


def test_order_id_does_not_trigger_tracking_verification() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    draft = "سفارش بررسی می‌شود."
    result = handle_manual_add_message(
        session,
        role="seller",
        text=f"سفارش {_ORDER_7}",
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package(draft),
    )
    assert result is not None
    assert result.used_tracking_reply is False
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    assert messages[1].source == AI_ASSISTED_DRAFT_SOURCE
    assert messages[1].text == draft


def test_live_and_replay_source_modes_do_not_auto_verify() -> None:
    settings = _auto_settings()
    assert (
        should_run_manual_sandbox_auto_tracking(
            source_mode="live_api_feed",
            role="seller",
            settings=settings,
        )
        is False
    )
    assert (
        should_run_manual_sandbox_auto_tracking(
            source_mode="historical_replay",
            role="seller",
            settings=settings,
        )
        is False
    )
    assert (
        should_run_manual_sandbox_auto_tracking(
            source_mode="manual_sandbox_chat",
            role="seller",
            settings=settings,
        )
        is True
    )


def test_verified_result_appends_tracking_aware_reply() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    result = handle_manual_add_message(
        session,
        role="seller",
        text=_TRACKING_24,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package(),
        verify_tracking_fn=_mock_verify_ok,
    )
    assert result and result.ai_message
    assert "استعلام شد" in result.ai_message.text
    assert "تحویل به واحد پست" in result.ai_message.text


def test_invalid_result_appends_not_confirmed_reply() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}

    def _verify(_code: str) -> IranPostTrackingResult:
        return _mock_verify_invalid(_code)

    messages: list[ManualChatMessage] = []
    seller = append_manual_chat_message(messages, sender_type="seller", text=_TRACKING_24)
    session[SESSION_MANUAL_CHAT_MESSAGES] = [message.to_dict() for message in messages]

    outcome = try_manual_sandbox_auto_tracking_verify(
        seller.text,
        seller_message_id=seller.message_id,
        session_state=session,
        settings=_auto_settings(),
        verify_fn=_verify,
    )
    reply = outcome.chat_reply
    assert reply is not None
    assert "تأیید نشد" in reply

    run_result = run_manual_assisted_auto_reply(
        messages,
        seller_message_id=seller.message_id,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        session_state=session,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package(),
        verify_tracking_fn=_mock_verify_invalid,
    )
    assert run_result.used_tracking_reply is True
    assert run_result.ai_message is not None
    assert "تأیید نشد" in run_result.ai_message.text


def test_timeout_result_appends_safe_fallback() -> None:
    reply = build_tracking_verification_chat_reply(_mock_verify_timeout(_TRACKING_24))
    assert "امکان استعلام" in reply


def test_dedupe_guard_prevents_duplicate_api_calls() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    calls = {"count": 0}

    def _counting_verify(_code: str) -> IranPostTrackingResult:
        calls["count"] += 1
        return _mock_verify_ok(_code)

    settings = _auto_settings()
    messages: list[ManualChatMessage] = []
    seller = append_manual_chat_message(messages, sender_type="seller", text=_TRACKING_24)
    session[SESSION_MANUAL_CHAT_MESSAGES] = [message.to_dict() for message in messages]

    first = try_manual_sandbox_auto_tracking_verify(
        seller.text,
        seller_message_id=seller.message_id,
        session_state=session,
        settings=settings,
        verify_fn=_counting_verify,
    )
    second = try_manual_sandbox_auto_tracking_verify(
        seller.text,
        seller_message_id=seller.message_id,
        session_state=session,
        settings=settings,
        verify_fn=_counting_verify,
    )
    assert first.attempted is True
    assert second.skipped_duplicate is True
    assert calls["count"] == 1


def test_result_panel_payload_excludes_pii() -> None:
    result = _mock_verify_ok(_TRACKING_24)
    payload = result.to_safe_dict()
    blob = json.dumps(payload, ensure_ascii=False)
    assert "ReceiverName" not in blob
    assert "SenderName" not in blob
    assert "PRIVATE" not in blob


def test_assisted_package_stored_when_tracking_runs() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    handle_manual_add_message(
        session,
        role="seller",
        text=_TRACKING_24,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package("draft-hidden"),
        verify_tracking_fn=_mock_verify_ok,
    )
    bucket = session.get(SESSION_MANUAL_ASSISTED_PACKAGES)
    assert isinstance(bucket, dict)
    assert "manual-room" in bucket


def test_tracking_reply_prevents_duplicate_assisted_bubble() -> None:
    session: dict[str, object] = {SESSION_MANUAL_CHAT_MESSAGES: []}
    result = handle_manual_add_message(
        session,
        role="seller",
        text=_TRACKING_24,
        room_id="manual-room",
        ticket_label=None,
        shop_id=None,
        settings=_auto_settings(),
        build_package_fn=_mock_build_package("draft-hidden"),
        verify_tracking_fn=_mock_verify_ok,
    )
    assert result and result.ai_message
    assert result.ai_message.source == IRAN_POST_TRACKING_SOURCE
    assert result.ai_message.text != "draft-hidden"
    messages = messages_from_session(session[SESSION_MANUAL_CHAT_MESSAGES])
    ai_messages = [message for message in messages if message.is_ai_generated]
    assert len(ai_messages) == 1


def test_build_tracking_verification_chat_reply_cases() -> None:
    verified = _mock_verify_ok(_TRACKING_24)
    assert "آخرین وضعیت مرسوله" in build_tracking_verification_chat_reply(verified)
    empty_events = parse_iran_post_response(
        {
            "Status": {"Code": "0", "Description": "OK"},
            "Parameters": {"AcceptanceDateTime": "2024-01-01"},
        },
        _TRACKING_24,
    )
    assert "اطلاعات مرسوله" in build_tracking_verification_chat_reply(empty_events)
