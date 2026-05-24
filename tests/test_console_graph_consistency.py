"""Tests for console vs agentic sandbox graph consistency diagnostics."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.agentic_sandbox.console_graph_consistency import (
    _FORBIDDEN_OUTPUT_KEYS,
    ComparedFieldStatus,
    ConsistencyStatus,
    ConsoleGraphConsistencyResult,
    _collect_json_keys,
    _compare_field,
    assert_console_graph_consistency_output_safe,
    build_console_interpretation_snapshot,
    build_graph_interpretation_snapshot,
    compare_console_graph_consistency,
    render_console_graph_consistency_markdown,
    summarize_console_graph_consistency_batch,
)
from app.config import AppSettings
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
)
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    sanitize_agentic_preview_result,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.intent_display import _OPEN_SNAPSHOT_ENTITY_SOURCE

# Expose helper for tests only — build minimal snapshots without full ticket graph.


def _interpretation_snapshot_from_values(**kwargs: object):
    from app.agentic_sandbox import console_graph_consistency as mod

    return mod._InterpretationSnapshot(
        detected_intent=kwargs.get("detected_intent"),  # type: ignore[arg-type]
        conceptual_intent_fa=kwargs.get("conceptual_intent_fa"),  # type: ignore[arg-type]
        suggested_action=kwargs.get("suggested_action"),  # type: ignore[arg-type]
        suggested_action_reason=kwargs.get("suggested_action_reason"),  # type: ignore[arg-type]
        actionability_actionable=kwargs.get("actionability_actionable"),  # type: ignore[arg-type]
        missing_required_entities=kwargs.get("missing_required_entities"),  # type: ignore[arg-type]
        entity_source=kwargs.get("entity_source"),  # type: ignore[arg-type]
        order_ids=kwargs.get("order_ids"),  # type: ignore[arg-type]
        product_ids=kwargs.get("product_ids"),  # type: ignore[arg-type]
        tracking_code=kwargs.get("tracking_code"),  # type: ignore[arg-type]
        knowledge_hint_count=kwargs.get("knowledge_hint_count"),  # type: ignore[arg-type]
        knowledge_hint_document_types=kwargs.get("knowledge_hint_document_types"),  # type: ignore[arg-type]
        safety_status=kwargs.get("safety_status"),  # type: ignore[arg-type]
        metadata=dict(kwargs.get("metadata") or {}),  # type: ignore[arg-type]
    )


def _ticket(**overrides: object) -> OperatorTicket:
    base = dict(
        room_id="ROOM_CG",
        ticket_label="support",
        route_label="general_vendor_support",
        assigned_department=None,
        review_priority=None,
        suggested_action="billing_review",
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview="لطفاً سفارش INC-7452190 را بررسی کنید",
        latest_vendor_message=None,
        recent_context_preview=None,
        detected_intent="settlement_status_inquiry",
        extracted_order_ids="7452190",
    )
    base.update(overrides)
    return OperatorTicket(**base)  # type: ignore[arg-type]


def _graph_preview(**overrides: object) -> AgenticSandboxPreviewResult:
    state = {
        "room_id": "ROOM_CG",
        "detected_intent": "settlement_status_inquiry",
        "conceptual_intent_fa": "پیگیری",
        "suggested_action": "billing_review",
        "suggested_action_reason": "fund_route",
        "actionability": {
            "actionability_actionable": True,
            "actionability_missing_entities": None,
            "actionability_validation_reason": "ok",
        },
        "extracted_entities": {
            "entity_source": ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
            "order_ids": ["7452190"],
            "product_ids": [],
        },
        "entity_extraction_source": ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
        "entity_extraction_source_char_count": 500,
        "display_preview_char_count": 200,
        "knowledge_hints": [],
        "draft_reply": "پاسخ",
        "safety_status": "passed",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "errors": [],
        "node_results": [{"node": "detect_intent", "status": "ok", "summary": "ok"}],
    }
    state.update(overrides)
    return sanitize_agentic_preview_result(state, knowledge_hints_enabled=False)  # type: ignore[arg-type]


def test_exact_match_marked_consistent() -> None:
    console = _interpretation_snapshot_from_values(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        order_ids="7452190",
        entity_source=ENTITY_SOURCE_FULL_FIRST_VENDOR,
        metadata={"console_entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR},
    )
    graph = _interpretation_snapshot_from_values(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        order_ids="7452190",
        entity_source=ENTITY_SOURCE_FULL_FIRST_VENDOR,
        metadata={"graph_entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR},
    )
    field = _compare_field(
        "detected_intent",
        console.detected_intent,
        graph.detected_intent,
        console=console,
        graph=graph,
    )
    assert field.status == ComparedFieldStatus.MATCH.value


def test_entity_source_difference_explainable_when_graph_full_first_turn() -> None:
    console = _interpretation_snapshot_from_values(
        entity_source=ENTITY_SOURCE_FULL_FIRST_VENDOR,
        order_ids="7452190",
        metadata={
            "console_entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR,
            "ai_assist_order_ids": "7452190",
        },
    )
    graph = _interpretation_snapshot_from_values(
        entity_source=ENTITY_SOURCE_FULL_FIRST_VENDOR,
        order_ids="7452190,7447698",
        metadata={"graph_entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR},
    )
    field = _compare_field(
        "order_ids",
        console.order_ids,
        graph.order_ids,
        console=console,
        graph=graph,
    )
    assert field.status == ComparedFieldStatus.EXPLAINABLE.value


def test_action_mismatch_marked_mismatch() -> None:
    console = _interpretation_snapshot_from_values(
        suggested_action="billing_review",
        metadata={},
    )
    graph = _interpretation_snapshot_from_values(
        suggested_action="escalate_to_supervisor",
        metadata={},
    )
    field = _compare_field(
        "suggested_action",
        console.suggested_action,
        graph.suggested_action,
        console=console,
        graph=graph,
    )
    assert field.status == ComparedFieldStatus.MISMATCH.value


def test_knowledge_hint_config_difference_explainable() -> None:
    console = _interpretation_snapshot_from_values(
        knowledge_hint_count="0",
        metadata={"knowledge_hints_enabled": False},
    )
    graph = _interpretation_snapshot_from_values(
        knowledge_hint_count="2",
        metadata={"knowledge_hints_enabled": True},
    )
    field = _compare_field(
        "knowledge_hint_count",
        console.knowledge_hint_count,
        graph.knowledge_hint_count,
        console=console,
        graph=graph,
    )
    assert field.status == ComparedFieldStatus.EXPLAINABLE.value


def test_batch_summary_counts_statuses() -> None:
    results = (
        ConsoleGraphConsistencyResult(
            room_id="A",
            consistency_status=ConsistencyStatus.CONSISTENT.value,
            compared_fields=(),
            mismatches=(),
            explanation_notes=(),
            safe_metadata={},
        ),
        ConsoleGraphConsistencyResult(
            room_id="B",
            consistency_status=ConsistencyStatus.MISMATCH.value,
            compared_fields=(),
            mismatches=("suggested_action",),
            explanation_notes=("mismatch_fields=suggested_action",),
            safe_metadata={},
        ),
    )
    summary = summarize_console_graph_consistency_batch(
        results,
        source_replay_path="replay.jsonl",
        source_redacted_path=None,
        provider="mock",
        knowledge_hints_enabled=False,
    )
    assert summary.status_counts[ConsistencyStatus.CONSISTENT.value] == 1
    assert summary.status_counts[ConsistencyStatus.MISMATCH.value] == 1


def test_reports_exclude_forbidden_fields() -> None:
    result = ConsoleGraphConsistencyResult(
        room_id="7743",
        consistency_status=ConsistencyStatus.CONSISTENT.value,
        compared_fields=(),
        mismatches=(),
        explanation_notes=(),
        safe_metadata={
            "graph_entity_extraction_source": ENTITY_SOURCE_FULL_FIRST_VENDOR,
            "console_ai_assist_entity_source": _OPEN_SNAPSHOT_ENTITY_SOURCE,
        },
    )
    md = render_console_graph_consistency_markdown(result)
    json_text = json.dumps(result.to_json_dict(), ensure_ascii=False)
    assert_console_graph_consistency_output_safe(md)
    assert_console_graph_consistency_output_safe(json_text)
    parsed = json.loads(json_text)
    assert not (_collect_json_keys(parsed) & _FORBIDDEN_OUTPUT_KEYS)


def test_compare_with_mocked_graph_preview() -> None:
    ticket = _ticket()
    preview = _graph_preview(room_id="ROOM_CG")
    settings = AppSettings(
        knowledge_hints_enabled=False,
        operator_agentic_sandbox_knowledge_hints_enabled=False,
        operator_agentic_sandbox_provider="mock",
    )
    with patch(
        "app.agentic_sandbox.console_graph_consistency.run_agentic_preview_for_ticket",
        return_value=preview,
    ):
        result = compare_console_graph_consistency(ticket, settings=settings, graph_preview=preview)
    assert result.room_id == "ROOM_CG"
    assert len(result.compared_fields) == 13
    assert result.consistency_status in {item.value for item in ConsistencyStatus}
    parsed = result.to_json_dict()
    assert not (_collect_json_keys(parsed) & _FORBIDDEN_OUTPUT_KEYS)


def test_sanitize_strips_full_text_from_graph_state_in_compare() -> None:
    state = {
        "room_id": "ROOM_CG",
        "full_first_vendor_message_text": "secret full message " * 50,
        "detected_intent": "settlement_status_inquiry",
        "suggested_action": "billing_review",
        "actionability": {"actionability_actionable": True},
        "extracted_entities": {"order_ids": ["7452190"]},
        "draft_reply": "x",
        "safety_status": "passed",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "errors": [],
        "node_results": [],
    }
    preview = sanitize_agentic_preview_result(state, knowledge_hints_enabled=False)
    graph = build_graph_interpretation_snapshot(preview)
    assert "secret full message" not in str(graph.metadata)


def test_build_console_snapshot_includes_ai_assist_metadata() -> None:
    ticket = _ticket()
    snap = build_console_interpretation_snapshot(
        ticket,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert snap.metadata.get("console_ai_assist_entity_source") == _OPEN_SNAPSHOT_ENTITY_SOURCE
    assert snap.metadata.get("ai_assist_order_ids") == "7452190"
