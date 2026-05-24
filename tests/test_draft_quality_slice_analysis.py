"""Tests for slice-based draft quality analysis."""

from __future__ import annotations

import json
from pathlib import Path

from app.evals.draft_quality_slice_analysis import (
    DEFAULT_MIN_SLICE_REVIEWS,
    actionability_slice_key,
    assert_slice_analysis_output_safe,
    build_draft_quality_slice_analysis_report,
    compute_draft_quality_slice_analysis,
    entity_presence_slice_key,
    format_draft_quality_slice_markdown,
    load_draft_enrichment_index,
)
from app.operator_console.draft_review_feedback import (
    DraftReviewFeedback,
    append_draft_review_feedback,
    build_draft_review_feedback_record,
)


def _row(
    *,
    room_id: str,
    suggested_action: str = "check_order_status",
    detected_intent: str = "order_status_review",
    conceptual_intent_fa: str | None = "پیگیری سفارش",
    draft_usable: bool = True,
    action_correct: bool = True,
    intent_correct: bool = True,
    entities_applicable: bool = True,
    entities_correct: bool | None = True,
    ticket_label: str | None = "support",
    too_verbose: bool = False,
    hallucination_detected: bool = False,
    unnecessary_followup_detected: bool = False,
    reviewer_note: str | None = None,
) -> DraftReviewFeedback:
    return DraftReviewFeedback(
        review_id=f"rev-{room_id}",
        timestamp_utc="2026-05-20T12:00:00+00:00",
        reviewer_id="local_operator",
        room_id=room_id,
        case_id=f"{room_id}__first_vendor_turn",
        draft_generation_mode="first_turn_only",
        draft_style="operational_short",
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        ticket_label=ticket_label,
        intent_correct=intent_correct,
        action_correct=action_correct,
        entities_applicable=entities_applicable,
        entities_correct=entities_correct,
        draft_usable=draft_usable,
        too_verbose=too_verbose,
        hallucination_detected=hallucination_detected,
        unnecessary_followup_detected=unnecessary_followup_detected,
        reviewer_note=reviewer_note,
    )


def test_slice_aggregation_by_suggested_action() -> None:
    rows = [
        _row(room_id="a", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="b", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="c", suggested_action="monitor", draft_usable=True, action_correct=True),
        _row(
            room_id="d",
            suggested_action="check_product_approval",
            draft_usable=True,
            entities_correct=False,
            reviewer_note="شناسه کالا استخراج نشد",
        ),
    ]
    summary = compute_draft_quality_slice_analysis(rows, min_slice_reviews=2)
    monitor = next(
        report
        for report in summary.slice_reports
        if report.slice_type == "suggested_action" and report.slice_key == "monitor"
    )
    assert monitor.total_reviews == 3
    assert monitor.usable_rate < 0.7
    assert monitor.is_weak


def test_weakest_slice_detection_respects_minimum_count() -> None:
    rows = [
        _row(room_id="only", suggested_action="check_return_request", draft_usable=False),
        _row(room_id="a", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="b", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="c", suggested_action="monitor", draft_usable=False, action_correct=False),
    ]
    summary = compute_draft_quality_slice_analysis(
        rows,
        min_slice_reviews=DEFAULT_MIN_SLICE_REVIEWS,
    )
    return_slice = next(
        report
        for report in summary.slice_reports
        if report.slice_type == "suggested_action" and report.slice_key == "check_return_request"
    )
    assert return_slice.total_reviews == 1
    assert return_slice not in summary.weakest_slices
    assert summary.weakest_slices[0].slice_key == "monitor"


def test_entity_and_actionability_slices_with_enrichment() -> None:
    row = _row(room_id="ROOM-X", suggested_action="update_delivery_status")
    enrichment = {
        "ROOM-X": {
            "route_label": "billing_review",
            "draft_extracted_order_ids": None,
            "draft_extracted_product_ids": None,
            "draft_extracted_tracking_code": None,
            "requires_identifier_request": True,
            "actionability_actionable": False,
        },
    }
    assert entity_presence_slice_key(row, enrichment["ROOM-X"]) == "no_entities"
    assert actionability_slice_key(row, enrichment["ROOM-X"]) == "missing_identifiers"

    summary = compute_draft_quality_slice_analysis([row], enrichment_index=enrichment)
    action_slice = next(
        report
        for report in summary.slice_reports
        if report.slice_type == "actionability" and report.slice_key == "missing_identifiers"
    )
    assert action_slice.total_reviews == 1
    route_slice = next(
        report
        for report in summary.slice_reports
        if report.slice_type == "route_label" and report.slice_key == "billing_review"
    )
    assert route_slice.total_reviews == 1


def test_markdown_rendering_and_output_safety() -> None:
    rows = [
        _row(room_id="1", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="2", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(room_id="3", suggested_action="monitor", draft_usable=False, action_correct=False),
        _row(
            room_id="4",
            conceptual_intent_fa="پیگیری مرجوعی سفارش",
            suggested_action="check_return_request",
            draft_usable=False,
            action_correct=False,
            entities_correct=False,
        ),
    ]
    summary = compute_draft_quality_slice_analysis(rows, min_slice_reviews=2)
    markdown = format_draft_quality_slice_markdown(summary)
    assert "# Draft Quality Slice Analysis" in markdown
    assert "Weakest slices" in markdown
    assert "Recommended calibration targets" in markdown
    assert "conversation transcript" not in markdown.lower()
    assert_slice_analysis_output_safe(markdown)


def test_empty_feedback_handling() -> None:
    summary = compute_draft_quality_slice_analysis([])
    assert summary.total_reviews == 0
    assert summary.overall_usable_rate == 0.0
    assert summary.weakest_slices == ()
    markdown = format_draft_quality_slice_markdown(summary)
    assert "No draft reviews" in markdown


def test_build_report_writes_files(tmp_path: Path) -> None:
    feedback = tmp_path / "reviews.jsonl"
    record = build_draft_review_feedback_record(
        room_id="ROOM-1",
        draft_generation_mode="first_turn_only",
        suggested_action="monitor",
        detected_intent="general_vendor_support",
        draft_usable=False,
        action_correct=False,
        intent_correct=True,
        entities_applicable=False,
        entities_correct=None,
        too_verbose=True,
        hallucination_detected=False,
    )
    append_draft_review_feedback(record, path=feedback)

    enrichment = tmp_path / "drafts.jsonl"
    enrichment.write_text(
        json.dumps(
            {
                "room_id": "ROOM-1",
                "route_label": "general_vendor_support",
                "draft_generated": True,
                "requires_identifier_request": False,
                "actionability_actionable": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.md"
    summary = build_draft_quality_slice_analysis_report(
        feedback,
        enrichment_path=enrichment,
        summary_output=summary_path,
        markdown_output=report_path,
        min_slice_reviews=1,
    )
    assert summary_path.is_file()
    assert report_path.is_file()
    assert summary.total_reviews == 1
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "slice_reports" in payload
    assert "recommended_calibration_targets" in payload


def test_load_enrichment_index(tmp_path: Path) -> None:
    path = tmp_path / "drafts.jsonl"
    path.write_text(
        json.dumps({"room_id": "R1", "draft_extracted_order_ids": "1234567"}) + "\n",
        encoding="utf-8",
    )
    index = load_draft_enrichment_index(path)
    assert "R1" in index
    assert index["R1"]["draft_extracted_order_ids"] == "1234567"
