"""Tests for operator-console agentic sandbox preview (session-only)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from app.agentic_sandbox.agentic_graph import build_safe_run_report
from app.config import AppSettings
from app.evals.first_turn_draft_context import ENTITY_SOURCE_FULL_FIRST_VENDOR
from app.operator_console.agentic_sandbox_preview import (
    SESSION_AGENTIC_PREVIEW_KEY,
    AgenticSandboxPreviewResult,
    _collect_mapping_keys,
    assert_agentic_preview_safe,
    build_agentic_preview_input_from_ticket,
    render_agentic_preview_markdown_or_lines,
    run_agentic_preview_for_ticket,
    sanitize_agentic_preview_result,
    store_session_agentic_preview,
    strip_internal_agentic_preview_state,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_operator_ticket_from_manual_chat,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import KnowledgeHint
from app.operator_console.manual_chat_models import ManualChatMessage


def _ticket(*, room_id: str = "7743", preview: str = "لطفاً تسویه را بررسی کنید") -> OperatorTicket:
    return OperatorTicket(
        room_id=room_id,
        ticket_label="fund",
        route_label="billing_review",
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
        original_vendor_issue_preview=preview,
        latest_vendor_message=None,
        recent_context_preview=None,
    )


def _final_state() -> dict[str, object]:
    return {
        "room_id": "7743",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "detected_intent": "settlement_status_inquiry",
        "conceptual_intent_fa": "پیگیری تسویه",
        "suggested_action": "billing_review",
        "suggested_action_reason": "fund_route",
        "actionability": {
            "actionability_actionable": True,
            "actionability_missing_entities": None,
            "actionability_validation_reason": "ok",
        },
        "extracted_entities": {
            "entity_source": "original_vendor_issue_preview",
            "order_ids": ["1234567"],
            "product_ids": [],
            "tracking_code": None,
            "tracking_carrier": None,
            "iban_masked": None,
            "warnings_summary": None,
        },
        "knowledge_hints": [
            {
                "document_type": "settlement_rules",
                "section_title": "تسویه",
                "source_lane": "official_policy",
                "priority_rank": 1,
                "snippet_chars": 120,
            },
        ],
        "draft_reply": "پاسخ کوتاه برای بررسی",
        "safety_status": "passed",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "errors": [],
        "node_results": [
            {"node": "build_first_turn_context", "status": "ok", "summary": "first_turn"},
            {"node": "detect_intent", "status": "ok", "summary": "intent"},
            {"node": "retrieve_knowledge_hints", "status": "ok", "summary": "hints=1"},
        ],
    }


def test_preview_disabled_by_default() -> None:
    settings = AppSettings()
    assert settings.operator_agentic_sandbox_preview_enabled is False


def test_preview_input_built_from_first_turn_safe_fields() -> None:
    settings = AppSettings(operator_agentic_sandbox_knowledge_hints_enabled=True)
    state = build_agentic_preview_input_from_ticket(_ticket(), settings=settings)
    assert state["room_id"] == "7743"
    assert state["knowledge_hints_enabled"] is True
    assert "seller issue" not in (state.get("first_turn_text") or "")
    assert state["first_turn_text"] == "لطفاً تسویه را بررسی کنید"
    assert state["execution_allowed"] is False
    assert state["customer_send_allowed"] is False


def test_preview_result_excludes_forbidden_fields() -> None:
    preview = sanitize_agentic_preview_result(
        _final_state(),
        knowledge_hints_enabled=True,
    )
    payload = json.dumps(preview.to_public_dict(), ensure_ascii=False)
    assert preview.draft_reply is not None
    assert "پاسخ کوتاه" in payload
    assert "messages" not in payload
    assert "conversation transcript" not in payload.lower()
    assert '"snippet"' not in payload
    assert "raw_prompt" not in payload
    assert preview.knowledge_hint_count == 1
    assert preview.knowledge_hint_document_types == ("settlement_rules",)
    assert preview.draft_char_count > 0
    assert_agentic_preview_safe(preview)


def test_unsafe_draft_not_in_preview_result() -> None:
    state = _final_state()
    state["draft_reply"] = "See conversation transcript for full details."
    state["safety_status"] = "failed"
    preview = sanitize_agentic_preview_result(state, knowledge_hints_enabled=True)
    assert preview.draft_reply is None


def test_safe_draft_included_after_safety_validation() -> None:
    preview = sanitize_agentic_preview_result(_final_state(), knowledge_hints_enabled=True)
    assert preview.draft_reply == "پاسخ کوتاه برای بررسی"
    assert preview.customer_send_allowed is False
    assert preview.execution_allowed is False


def test_safety_flags_enforced() -> None:
    preview = sanitize_agentic_preview_result(
        _final_state(),
        knowledge_hints_enabled=True,
    )
    assert_agentic_preview_safe(preview)

    unsafe = AgenticSandboxPreviewResult(
        room_id="7743",
        graph_status="failed",
        node_statuses={},
        node_summaries=(),
        detected_intent=None,
        conceptual_intent_fa=None,
        suggested_action=None,
        suggested_action_reason=None,
        actionability_actionable=None,
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
        knowledge_hints_enabled=True,
        knowledge_hint_count=0,
        knowledge_hint_document_types=(),
        draft_char_count=0,
        safety_status=None,
        human_review_required=False,
        execution_allowed=True,
        customer_send_allowed=False,
        errors=(),
        draft_reply=None,
        draft_style=None,
        draft_is_mock=False,
    )
    with pytest.raises(ValueError, match="execution_allowed"):
        assert_agentic_preview_safe(unsafe)


def test_session_safe_result_contains_node_statuses() -> None:
    preview = sanitize_agentic_preview_result(
        _final_state(),
        knowledge_hints_enabled=True,
    )
    session: dict[str, object] = {}
    store_session_agentic_preview(session, preview)
    bucket = session[SESSION_AGENTIC_PREVIEW_KEY]
    assert isinstance(bucket, dict)
    stored = bucket["7743"]
    assert isinstance(stored, AgenticSandboxPreviewResult)
    assert stored.node_statuses.get("detect_intent") == "ok"
    lines = render_agentic_preview_markdown_or_lines(stored)
    joined = "\n".join(lines)
    assert "detect_intent" in joined
    assert "settlement_rules" in joined


def test_closed_ticket_preview_skips_graph_and_draft() -> None:
    settings = AppSettings(
        multi_turn_context_enabled=True,
        operator_agentic_sandbox_provider="mock",
    )
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
    with patch(
        "app.agentic_sandbox.agentic_graph.run_agentic_sandbox_workflow",
    ) as run_graph:
        preview = run_agentic_preview_for_ticket(
            ticket,
            settings=settings,
            conversation_snapshot=snapshot,
            source_mode="manual_sandbox_chat",
        )
    run_graph.assert_not_called()
    assert preview.multi_turn_should_generate_draft is False
    assert preview.multi_turn_skip_reason == "closed_ticket"
    assert preview.draft_reply is None
    assert preview.graph_status == "skipped"
    assert preview.draft_char_count == 0


def test_run_preview_uses_graph_without_persisting() -> None:
    settings = AppSettings(
        operator_agentic_sandbox_preview_enabled=True,
        operator_agentic_sandbox_provider="mock",
        operator_agentic_sandbox_knowledge_hints_enabled=True,
    )
    mock_hint = KnowledgeHint(
        document_type="settlement_rules",
        section_title="تسویه",
        source_lane="official_policy",
        priority_rank=1,
        snippet="must not leak",
        score=0.9,
    )

    with (
        patch(
            "app.agentic_sandbox.agentic_graph.run_agentic_sandbox_workflow",
            return_value=_final_state(),
        ),
        patch(
            "app.operator_console.knowledge_hints.fetch_knowledge_hints_for_ticket",
            return_value=(mock_hint,),
        ),
        patch(
            "app.evals.first_turn_draft_context.fetch_knowledge_hints_for_ticket",
            return_value=(mock_hint,),
        ),
    ):
        preview = run_agentic_preview_for_ticket(_ticket(), settings=settings)

    assert preview.room_id == "7743"
    assert preview.graph_status == "ok"
    assert "must not leak" not in json.dumps(preview.to_public_dict())


def _state_with_full_first_turn() -> dict[str, object]:
    full_text = "x" * 500 + " INC-7452190 " + "y" * 400 + " INC-7447698"
    state = _final_state()
    state.update(
        {
            "full_first_vendor_message_text": full_text,
            "first_turn_extraction_text": full_text,
            "entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR,
            "entity_extraction_source_char_count": len(full_text),
            "display_preview_char_count": 200,
            "human_review_payload": {
                "room_id": "7743",
                "full_first_vendor_message_text": full_text,
                "entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR,
            },
        },
    )
    return state


def test_sanitize_strips_full_first_vendor_message_text() -> None:
    state = _state_with_full_first_turn()
    stripped = strip_internal_agentic_preview_state(state)
    assert "full_first_vendor_message_text" not in stripped
    assert "first_turn_extraction_text" not in stripped
    assert "human_review_payload" not in stripped

    preview = sanitize_agentic_preview_result(state, knowledge_hints_enabled=True)
    payload = preview.to_public_dict()
    assert "full_first_vendor_message_text" not in payload
    assert preview.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    full_text = str(state["full_first_vendor_message_text"])
    assert preview.entity_extraction_source_char_count == len(full_text)
    assert preview.display_preview_char_count == 200
    assert full_text not in json.dumps(payload, ensure_ascii=False)


def test_safety_passes_when_entity_source_label_is_full_first_vendor() -> None:
    preview = sanitize_agentic_preview_result(
        _state_with_full_first_turn(),
        knowledge_hints_enabled=True,
    )
    assert_agentic_preview_safe(preview)
    assert preview.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR


def test_session_preview_excludes_full_first_turn_text() -> None:
    preview = sanitize_agentic_preview_result(
        _state_with_full_first_turn(),
        knowledge_hints_enabled=True,
    )
    session: dict[str, object] = {}
    store_session_agentic_preview(session, preview)
    stored = session[SESSION_AGENTIC_PREVIEW_KEY]["7743"]  # type: ignore[index]
    public = stored.to_public_dict()  # type: ignore[union-attr]
    assert "full_first_vendor_message_text" not in _collect_mapping_keys(public)
    assert public.get("entity_extraction_source") == ENTITY_SOURCE_FULL_FIRST_VENDOR


def test_handoff_report_excludes_full_first_turn_text() -> None:
    state = _state_with_full_first_turn()
    report = build_safe_run_report(state)
    assert "full_first_vendor_message_text" not in _collect_mapping_keys(report)
    handoff = report.get("human_review_payload") or {}
    assert isinstance(handoff, dict)
    assert "full_first_vendor_message_text" not in _collect_mapping_keys(handoff)
    assert report.get("entity_extraction_source") == ENTITY_SOURCE_FULL_FIRST_VENDOR


def test_forbidden_key_in_public_dict_still_fails_safety() -> None:
    preview = sanitize_agentic_preview_result(
        _final_state(),
        knowledge_hints_enabled=True,
    )
    leaked_public = preview.to_public_dict()
    leaked_public["full_first_vendor_message_text"] = "leak"

    class _LeakProbe:
        execution_allowed = preview.execution_allowed
        customer_send_allowed = preview.customer_send_allowed
        human_review_required = preview.human_review_required

        def to_public_dict(self) -> dict[str, object]:
            return leaked_public

    with pytest.raises(ValueError, match="forbidden key"):
        assert_agentic_preview_safe(_LeakProbe())  # type: ignore[arg-type]
