"""Tests for controlled read-only tool execution inside agentic graph (Step 235)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from app.agentic_sandbox.agentic_graph import (
    build_safe_run_report,
    initial_state_from_ticket,
    run_agentic_sandbox_workflow,
)
from app.config import AppSettings
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.console_models import OperatorTicket
from app.operator_console.manual_chat_models import ManualChatMessage
from app.operator_console.manual_chat_sandbox import _complete_seller_turn_with_reply


def _ticket(first_turn: str = "سفارش INC-7358954 تحویل شد") -> OperatorTicket:
    return OperatorTicket(
        room_id="ROOM-TOOLS-1",
        ticket_label="support",
        route_label="general_vendor_support",
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
        original_vendor_issue_preview=first_turn,
        latest_vendor_message=None,
        recent_context_preview=None,
    )


def _mock_generate(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
    _ = messages
    return LLMResponse(
        content='{"conceptual_intent_fa":"ارسال","draft_reply":"پاسخ عمومی"}',
        provider=provider,
        model=model,
        metadata={},
    )


@dataclass(frozen=True)
class _FakeLookupResult:
    payload: dict

    def to_safe_dict(self) -> dict:
        return dict(self.payload)


@dataclass(frozen=True)
class _FakeTrackingResult:
    payload: dict

    def to_safe_dict(self) -> dict:
        return dict(self.payload)


def _settings(**overrides: object) -> AppSettings:
    base = {
        "agentic_graph_read_only_tools_enabled": True,
        "agentic_graph_tool_execution_source_modes": "manual_sandbox_chat",
        "agentic_graph_order_lookup_enabled": True,
        "agentic_graph_iran_post_verify_enabled": True,
        "inchand_order_lookup_enabled": True,
        "iran_post_tracking_enabled": True,
        "inchand_api_key_value": "token",
        "iran_post_tracking_token": "token",
        "shipment_delivery_decision_enabled": True,
        "knowledge_hints_enabled": False,
    }
    base.update(overrides)
    return AppSettings(**base)


def test_graph_tools_disabled_no_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"lookup": 0}

    def _lookup(*args, **kwargs):  # noqa: ANN002, ANN003
        called["lookup"] += 1
        return _FakeLookupResult({"found": False})

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings(agentic_graph_read_only_tools_enabled=False)
    initial = initial_state_from_ticket(
        _ticket("سفارش INC-7358954 تحویل شد"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("graph_tools_enabled") is False
    assert called["lookup"] == 0


def test_graph_tools_enabled_but_live_source_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"lookup": 0}

    def _lookup(*args, **kwargs):  # noqa: ANN002, ANN003
        called["lookup"] += 1
        return _FakeLookupResult({"found": False})

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سفارش INC-7358954 تحویل شد"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="live_api_feed",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("graph_tools_enabled") is False
    assert called["lookup"] == 0


def test_manual_sandbox_order_lookup_executes_when_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _extract_entities(_state):  # noqa: ANN001
        return {
            "extracted_entities": {
                "entity_source": "test",
                "order_ids": ["INC-7358954"],
                "product_ids": [],
                "tracking_code": None,
                "tracking_carrier": None,
                "iban_masked": None,
                "warnings_summary": None,
            },
            "node_results": [],
        }

    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "is_delivered_in_inchand": True,
                "primary_parcel_tracking_code": None,
                "order_status": "تحویل شده",
            },
        )

    monkeypatch.setattr(
        "app.agentic_sandbox.agentic_nodes.extract_entities_node",
        _extract_entities,
    )
    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سفارش 7358954 تحویل شد"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert isinstance(final.get("order_lookup_result"), dict)
    assert final["order_lookup_result"]["found"] is True


def test_delivered_order_skips_iran_post_and_uses_grounded_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _extract_entities(_state):  # noqa: ANN001
        return {
            "extracted_entities": {
                "entity_source": "test",
                "order_ids": ["INC-7358954"],
                "product_ids": [],
                "tracking_code": None,
                "tracking_carrier": None,
                "iban_masked": None,
                "warnings_summary": None,
            },
            "node_results": [],
        }

    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "is_delivered_in_inchand": True,
                "primary_parcel_tracking_code": None,
                "order_status": "تحویل شده",
            },
        )

    def _verify(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Iran Post should be skipped for delivered order")

    monkeypatch.setattr(
        "app.agentic_sandbox.agentic_nodes.extract_entities_node",
        _extract_entities,
    )
    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.verify_iran_post_tracking_code", _verify)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سفارش 7358954 تحویل شد"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("tool_grounded_reply_used") is True
    assert "وضعیت مرسوله: تحویل شده" in (final.get("draft_reply") or "")


def test_graph_sets_order_lookup_state_before_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "is_delivered_in_inchand": True,
                "order_status": "تحویل شده",
            },
        )

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سفارش INC-7358954 تحویل شده لطفا اعمال بفرمایید"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    metadata = final.get("graph_tool_metadata") or {}
    assert metadata.get("order_lookup_executed") is True
    assert metadata.get("order_lookup_result_present_before_decision") is True
    assert metadata.get("order_lookup_found_before_decision") is True
    assert metadata.get("order_lookup_delivered_before_decision") is True


def test_decision_node_marks_lookup_source_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "is_delivered_in_inchand": True,
                "order_status": "تحویل شده",
            },
        )

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سلام وقت بخیر، سفارش شماره INC-7358954 تحویل شده لطفا اعمال بفرمایید"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("order_lookup_auto_triggered") is True
    assert final.get("order_lookup_result_source") == "graph_auto"
    assert final.get("decision_used_order_lookup_result") is True


def test_multi_order_graph_metadata_exposed_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "is_delivered_in_inchand": True,
                "order_status": "تحویل شده",
                "primary_provider_status": "تحویل شده",
                "primary_parcel_status_name": "تحویل مشتری",
            },
        )

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings(multi_order_batch_enabled=True)
    initial = initial_state_from_ticket(
        _ticket("INC-7358055 و INC-7357421 تحویل شده لطفا اعمال بفرمایید"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("multi_order_decision_type") == "multi_order_all_delivered"
    assert final.get("multi_order_reply_used") is True
    summary = final.get("multi_order_summary") or {}
    assert summary.get("batch_count") == 2


def test_reports_exclude_raw_tool_payload_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    def _lookup(order_id: str, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeLookupResult(
            {
                "order_id": order_id,
                "found": True,
                "receiver_name": "private",
                "is_delivered_in_inchand": False,
            },
        )

    monkeypatch.setattr("app.agentic_sandbox.agentic_nodes.lookup_inchand_order", _lookup)
    settings = _settings()
    initial = initial_state_from_ticket(
        _ticket("سفارش INC-7358954 ارسال شد"),
        generate_fn=_mock_generate,
        settings=settings,
        source_mode="manual_sandbox_chat",
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    report = build_safe_run_report(final)
    assert "receiver_name" not in str(report)


def _fake_graph_package() -> AgenticAssistedPackage:
    preview = AgenticSandboxPreviewResult(
        room_id="manual-room",
        graph_status="ok",
        node_statuses={},
        node_summaries=(),
        detected_intent="delivery",
        conceptual_intent_fa=None,
        suggested_action="record_update",
        suggested_action_reason=None,
        actionability_actionable=True,
        missing_required_entities=None,
        actionability_validation_reason=None,
        entity_source="first_turn",
        entity_extraction_source="first_turn",
        entity_extraction_source_char_count=20,
        display_preview_char_count=20,
        order_id_count=1,
        product_id_count=0,
        extracted_order_ids="INC-7358954",
        extracted_product_ids=None,
        extracted_tracking_code=None,
        extracted_tracking_carrier=None,
        extracted_iban_masked=None,
        entity_warnings_summary=None,
        knowledge_hints_enabled=False,
        knowledge_hint_count=0,
        knowledge_hint_document_types=(),
        draft_char_count=30,
        safety_status="passed",
        human_review_required=True,
        execution_allowed=False,
        customer_send_allowed=False,
        errors=(),
        draft_reply="وضعیت مرسوله: تحویل شده. درخواست شما ثبت و در دست بررسی قرار گرفت.",
        final_reflected_draft="وضعیت مرسوله: تحویل شده. درخواست شما ثبت و در دست بررسی قرار گرفت.",
        draft_provider="mock",
        graph_tools_enabled=True,
        graph_tools_planned=("inchand_order_lookup",),
        graph_tools_executed=("inchand_order_lookup",),
        graph_tools_blocked=(),
        graph_tools_blocked_reasons={},
        shipment_delivery_decision_type="order_already_delivered_in_inchand",
        tool_grounded_reply_used=True,
        order_lookup_found=True,
        order_delivered_in_inchand=True,
        parcel_tracking_code_present=False,
        iran_post_verified=None,
    )
    return AgenticAssistedPackage(
        room_id="manual-room",
        graph=preview,
        operator_checklist=(),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )


def test_manual_sandbox_uses_graph_final_draft_without_outer_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _build_package(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        return _fake_graph_package()

    def _should_not_be_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("outer shipment decision should be bypassed")

    monkeypatch.setattr(
        "app.operator_console.manual_chat_sandbox.try_manual_sandbox_shipment_decision",
        _should_not_be_called,
    )
    messages = [
        ManualChatMessage(
            message_id="m1",
            sender_type="seller",
            text="سفارش INC-7358954 تحویل شد",
            created_at="2026-05-27T00:00:00+00:00",
        ),
    ]
    session_state: dict[str, object] = {}
    settings = _settings()
    result = _complete_seller_turn_with_reply(
        messages,
        seller_message_id="m1",
        room_id="manual-room",
        ticket_label="support",
        shop_id=None,
        session_state=session_state,
        settings=settings,
        build_package_fn=_build_package,
    )
    assert result.success is True
    assert result.reply_origin == "graph_read_only_tools"
    assert messages[-1].text.startswith("وضعیت مرسوله")
