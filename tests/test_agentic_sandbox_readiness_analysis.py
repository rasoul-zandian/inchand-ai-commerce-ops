"""Tests for agentic sandbox node-level readiness analysis."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.agentic_readiness_analysis import (
    BUCKET_DRAFT_MISSING_OR_INVALID,
    BUCKET_NEEDS_KNOWLEDGE_REVIEW,
    BUCKET_NEEDS_MISSING_IDENTIFIER,
    BUCKET_NODE_ERROR,
    BUCKET_READY_FOR_HUMAN_REVIEW,
    BUCKET_SAFETY_FAILED,
    BatchRunRecord,
    assert_readiness_output_safe,
    build_agentic_readiness_report,
    classify_readiness_bucket,
    is_ready_for_human_review,
    load_batch_run_records,
    render_agentic_readiness_markdown,
    summarize_agentic_readiness,
)
from app.config import AppSettings


def _all_ok_nodes() -> dict[str, str]:
    return {
        "build_first_turn_context": "ok",
        "detect_intent": "ok",
        "extract_entities": "ok",
        "retrieve_knowledge_hints": "ok",
        "suggest_action": "ok",
        "validate_actionability": "ok",
        "generate_draft": "ok",
        "safety_gate": "ok",
        "human_review_handoff": "ok",
    }


def _base_row(**overrides: object) -> BatchRunRecord:
    data: dict[str, object] = {
        "room_id": "ROOM1",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "node_statuses": _all_ok_nodes(),
        "safety_status": "passed",
        "detected_intent": "delivery_confirmation_request",
        "conceptual_intent_fa": "ثبت تحویل",
        "suggested_action": "update_delivery_status",
        "actionability_actionable": True,
        "missing_required_entities": None,
        "order_id_count": 1,
        "product_id_count": 0,
        "has_tracking_code": False,
        "knowledge_hint_count": 1,
        "draft_char_count": 120,
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "success": True,
        "errors": [],
    }
    data.update(overrides)
    record = BatchRunRecord.from_json_dict(data)
    assert record is not None
    return record


def test_all_ok_run_marked_ready_for_human_review() -> None:
    row = _base_row()
    assert is_ready_for_human_review(row) is True
    assignment = classify_readiness_bucket(row)
    assert assignment.bucket == BUCKET_READY_FOR_HUMAN_REVIEW


def test_missing_identifier_run_bucketed_correctly() -> None:
    row = _base_row(
        actionability_actionable=False,
        missing_required_entities="order_id",
        draft_char_count=0,
    )
    assert is_ready_for_human_review(row) is False
    assignment = classify_readiness_bucket(row)
    assert assignment.bucket == BUCKET_DRAFT_MISSING_OR_INVALID

    row_with_draft = _base_row(
        actionability_actionable=False,
        missing_required_entities="order_id",
        draft_char_count=180,
    )
    assert is_ready_for_human_review(row_with_draft) is True
    assignment_draft = classify_readiness_bucket(row_with_draft)
    assert assignment_draft.bucket == BUCKET_READY_FOR_HUMAN_REVIEW
    assert assignment_draft.reason == "identifier_request_draft_ready"


def test_no_knowledge_policy_intent_bucketed_needs_knowledge_review() -> None:
    row = _base_row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        knowledge_hint_count=0,
        draft_char_count=0,
        node_statuses={
            **_all_ok_nodes(),
            "generate_draft": "ok",
        },
    )
    assignment = classify_readiness_bucket(row)
    assert assignment.bucket == BUCKET_DRAFT_MISSING_OR_INVALID

    row_no_draft_but_other_issue = _base_row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        knowledge_hint_count=0,
        human_review_required=False,
        draft_char_count=100,
    )
    assignment2 = classify_readiness_bucket(row_no_draft_but_other_issue)
    assert assignment2.bucket == BUCKET_NEEDS_KNOWLEDGE_REVIEW


def test_node_error_counted_by_node() -> None:
    nodes = _all_ok_nodes()
    nodes["detect_intent"] = "failed"
    row = _base_row(node_statuses=nodes, draft_char_count=0)
    summary = summarize_agentic_readiness([row], source_batch_runs_path="test.jsonl")
    assert summary.node_error_counts.get("detect_intent") == 1
    assert classify_readiness_bucket(row).bucket == BUCKET_NODE_ERROR


def test_safety_failed_bucketed_correctly() -> None:
    row = _base_row(safety_status="blocked", draft_char_count=100)
    assignment = classify_readiness_bucket(row)
    assert assignment.bucket == BUCKET_SAFETY_FAILED
    summary = summarize_agentic_readiness([row], source_batch_runs_path="test.jsonl")
    assert summary.readiness_buckets[BUCKET_SAFETY_FAILED] == 1


def test_markdown_excludes_forbidden_raw_fields() -> None:
    row = _base_row()
    summary = summarize_agentic_readiness([row], source_batch_runs_path="test.jsonl")
    markdown = render_agentic_readiness_markdown(summary)
    lowered = markdown.lower()
    assert "draft_response" not in lowered
    assert "conversation transcript" not in lowered
    assert '"messages"' not in lowered
    assert_readiness_output_safe(markdown)


def test_empty_input_handled() -> None:
    summary = summarize_agentic_readiness([], source_batch_runs_path="empty.jsonl")
    assert summary.total_runs == 0
    assert summary.human_review_ready_rate == 0.0
    assert summary.readiness_buckets[BUCKET_READY_FOR_HUMAN_REVIEW] == 0
    markdown = render_agentic_readiness_markdown(summary)
    assert "total_runs:** 0" in markdown


def test_missing_identifier_by_entity_aggregated() -> None:
    rows = [
        _base_row(
            room_id="A",
            actionability_actionable=False,
            missing_required_entities="order_id",
            draft_char_count=0,
        ),
        _base_row(
            room_id="B",
            actionability_actionable=False,
            missing_required_entities="order_id, product_id",
            draft_char_count=0,
        ),
    ]
    summary = summarize_agentic_readiness(rows, source_batch_runs_path="test.jsonl")
    assert summary.missing_identifier_count == 2
    assert summary.missing_identifier_by_entity["order_id"] == 2
    assert summary.missing_identifier_by_entity["product_id"] == 1


def test_build_report_from_jsonl(tmp_path: Path) -> None:
    batch_path = tmp_path / "batch.jsonl"
    batch_path.write_text(
        json.dumps(
            {
                "room_id": "99",
                "node_statuses": _all_ok_nodes(),
                "safety_status": "passed",
                "detected_intent": "general_question",
                "suggested_action": "human_followup",
                "actionability_actionable": True,
                "knowledge_hint_count": 0,
                "draft_char_count": 50,
                "human_review_required": True,
                "execution_allowed": False,
                "customer_send_allowed": False,
                "success": True,
                "errors": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    markdown_path = tmp_path / "report.md"
    settings = AppSettings(draft_hard_max_chars=300)
    summary = build_agentic_readiness_report(
        batch_path,
        summary_output=summary_path,
        markdown_output=markdown_path,
        settings=settings,
    )
    assert summary.total_runs == 1
    assert summary_path.is_file()
    assert markdown_path.is_file()
    loaded = load_batch_run_records(batch_path)
    assert len(loaded) == 1


def test_needs_missing_identifier_bucket_without_draft_path() -> None:
    row = _base_row(
        actionability_actionable=False,
        missing_required_entities="product_id",
        human_review_required=False,
        draft_char_count=50,
        knowledge_hint_count=1,
    )
    assignment = classify_readiness_bucket(row)
    assert assignment.bucket == BUCKET_NEEDS_MISSING_IDENTIFIER
