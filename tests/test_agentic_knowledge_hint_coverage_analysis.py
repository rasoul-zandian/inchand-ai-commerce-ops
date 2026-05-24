"""Tests for agentic sandbox knowledge hint coverage diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.agentic_readiness_analysis import BatchRunRecord
from app.agentic_sandbox.knowledge_hint_coverage_analysis import (
    GAP_KNOWLEDGE_INDEX_GAP,
    GAP_MISSING_QUERY_TERMS,
    GAP_QUERY_NORMALIZATION_GAP,
    GAP_RETRIEVAL_FILTER_TOO_STRICT,
    assert_coverage_output_safe,
    build_knowledge_hint_coverage_report,
    build_zero_hint_run,
    infer_gap_reason,
    is_policy_relevant_run,
    render_knowledge_hint_coverage_markdown,
    summarize_knowledge_hint_coverage,
)


def _row(**overrides: object) -> BatchRunRecord:
    data: dict[str, object] = {
        "room_id": "ROOM1",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "node_statuses": {},
        "safety_status": "passed",
        "detected_intent": "general_vendor_support",
        "conceptual_intent_fa": "پشتیبانی عمومی فروشنده",
        "suggested_action": "monitor",
        "actionability_actionable": True,
        "missing_required_entities": None,
        "order_id_count": 0,
        "product_id_count": 0,
        "has_tracking_code": False,
        "knowledge_hint_count": 0,
        "draft_char_count": 100,
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


def test_policy_relevance_detection() -> None:
    settlement = _row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        ticket_label="fund",
        route_label="billing_review",
        conceptual_intent_fa="پیگیری تسویه حساب",
    )
    assert is_policy_relevant_run(settlement) is True

    generic = _row(
        detected_intent="seller_notification",
        suggested_action="record_update",
        conceptual_intent_fa="اطلاع فروشنده",
    )
    assert is_policy_relevant_run(generic) is False

    product = _row(
        detected_intent="general_vendor_support",
        conceptual_intent_fa="درخواست ویرایش کالا",
    )
    assert is_policy_relevant_run(product) is True


def test_coverage_rate_calculation() -> None:
    rows = [
        _row(
            room_id="A",
            detected_intent="settlement_status_inquiry",
            suggested_action="billing_review",
            ticket_label="fund",
            route_label="billing_review",
            conceptual_intent_fa="پیگیری تسویه حساب",
            knowledge_hint_count=0,
        ),
        _row(
            room_id="B",
            detected_intent="settlement_panel_access_issue",
            suggested_action="check_settlement_status",
            conceptual_intent_fa="پیگیری تسویه حساب",
            knowledge_hint_count=2,
        ),
        _row(
            room_id="C",
            detected_intent="seller_notification",
            suggested_action="record_update",
            knowledge_hint_count=0,
        ),
    ]
    summary = summarize_knowledge_hint_coverage(rows, source_batch_runs_path="test.jsonl")
    assert summary.policy_relevant_runs == 2
    assert summary.runs_with_hints == 1
    assert summary.coverage_rate == 0.5


def test_zero_hint_run_listing() -> None:
    row = _row(
        room_id="47029",
        detected_intent="settlement_panel_access_issue",
        suggested_action="check_settlement_status",
        conceptual_intent_fa="پیگیری تسویه حساب",
        knowledge_hint_count=0,
    )
    summary = summarize_knowledge_hint_coverage([row], source_batch_runs_path="test.jsonl")
    assert len(summary.zero_hint_policy_runs) == 1
    zero = summary.zero_hint_policy_runs[0]
    assert zero.room_id == "47029"
    assert zero.knowledge_hint_count == 0
    assert zero.reason_hint


def test_gap_reason_settlement_normalization() -> None:
    row = _row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        ticket_label="fund",
        route_label="billing_review",
        conceptual_intent_fa="پیگیری تصفیه حساب",
        knowledge_hint_count=0,
    )
    assert infer_gap_reason(row) == GAP_QUERY_NORMALIZATION_GAP
    zero = build_zero_hint_run(row)
    assert zero.reason_hint == GAP_QUERY_NORMALIZATION_GAP


def test_gap_reason_missing_document_type() -> None:
    row = _row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        ticket_label="fund",
        route_label="billing_review",
        conceptual_intent_fa="پیگیری تسویه حساب",
        knowledge_hint_count=0,
    )
    assert infer_gap_reason(row) == GAP_RETRIEVAL_FILTER_TOO_STRICT

    support_settlement = _row(
        detected_intent="settlement_panel_access_issue",
        suggested_action="check_settlement_status",
        conceptual_intent_fa="پیگیری تسویه حساب",
        ticket_label="support",
        route_label="general_vendor_support",
        knowledge_hint_count=0,
    )
    assert infer_gap_reason(support_settlement) == GAP_KNOWLEDGE_INDEX_GAP


def test_gap_reason_missing_query_terms() -> None:
    row = _row(
        detected_intent="product_approval_review",
        suggested_action="check_product_approval",
        conceptual_intent_fa="پشتیبانی عمومی فروشنده",
        knowledge_hint_count=0,
    )
    assert infer_gap_reason(row) == GAP_MISSING_QUERY_TERMS


def test_markdown_excludes_raw_content() -> None:
    row = _row(
        detected_intent="settlement_status_inquiry",
        suggested_action="billing_review",
        ticket_label="fund",
        conceptual_intent_fa="پیگیری تسویه حساب",
    )
    summary = summarize_knowledge_hint_coverage([row], source_batch_runs_path="test.jsonl")
    markdown = render_knowledge_hint_coverage_markdown(summary)
    lowered = markdown.lower()
    assert "draft_response" not in lowered
    assert "conversation transcript" not in lowered
    assert '"messages"' not in lowered
    assert "original_vendor" not in lowered
    assert_coverage_output_safe(markdown)


def test_empty_input_handling() -> None:
    summary = summarize_knowledge_hint_coverage([], source_batch_runs_path="empty.jsonl")
    assert summary.total_runs == 0
    assert summary.policy_relevant_runs == 0
    assert summary.coverage_rate == 0.0
    assert summary.zero_hint_policy_runs == ()
    markdown = render_knowledge_hint_coverage_markdown(summary)
    assert "total_runs:** 0" in markdown


def test_build_report_from_jsonl(tmp_path: Path) -> None:
    batch_path = tmp_path / "batch.jsonl"
    batch_path.write_text(
        json.dumps(
            {
                "room_id": "99",
                "ticket_label": "fund",
                "route_label": "billing_review",
                "detected_intent": "settlement_status_inquiry",
                "conceptual_intent_fa": "پیگیری تسویه حساب",
                "suggested_action": "billing_review",
                "knowledge_hint_count": 0,
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
    summary = build_knowledge_hint_coverage_report(
        batch_path,
        summary_output=summary_path,
        markdown_output=markdown_path,
    )
    assert summary.policy_relevant_runs == 1
    assert summary_path.is_file()
    assert markdown_path.is_file()
