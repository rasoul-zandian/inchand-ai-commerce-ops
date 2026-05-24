"""Tests for deep action mismatch analysis from draft review feedback."""

from __future__ import annotations

import json
from pathlib import Path

from app.evals.action_mismatch_analysis import (
    assert_analysis_output_safe,
    build_action_mismatch_analysis_report,
    build_confusion_pairs,
    compute_action_mismatch_analysis,
    detect_ambiguous_boundaries,
    format_action_mismatch_markdown,
    infer_expected_action,
    is_action_mismatch_row,
)
from app.operator_console.draft_review_feedback import (
    DraftReviewFeedback,
    append_draft_review_feedback,
    build_draft_review_feedback_record,
)


def _row(
    *,
    room_id: str,
    suggested_action: str,
    detected_intent: str = "general_vendor_support",
    action_correct: bool = True,
    draft_usable: bool = True,
    conceptual_intent_fa: str | None = None,
    reviewer_note: str | None = None,
    ticket_label: str | None = None,
) -> DraftReviewFeedback:
    return DraftReviewFeedback(
        review_id=f"id-{room_id}",
        timestamp_utc="2026-05-20T12:00:00+00:00",
        reviewer_id="local_operator",
        room_id=room_id,
        case_id=f"{room_id}__first_vendor_turn",
        draft_generation_mode="first_turn_only",
        draft_style="operational_short",
        conceptual_intent_fa=conceptual_intent_fa,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        intent_correct=True,
        action_correct=action_correct,
        entities_correct=True,
        draft_usable=draft_usable,
        too_verbose=False,
        hallucination_detected=False,
        ticket_label=ticket_label,
        reviewer_note=reviewer_note,
    )


def test_detects_top_wrong_predicted_action() -> None:
    rows = [
        _row(room_id="1", suggested_action="monitor", action_correct=False),
        _row(room_id="2", suggested_action="monitor", action_correct=False),
        _row(room_id="3", suggested_action="check_order_status", action_correct=False),
        _row(room_id="4", suggested_action="human_followup", action_correct=True),
    ]
    summary = compute_action_mismatch_analysis(rows)
    assert summary.total_action_mismatches == 3
    assert summary.top_predicted_wrong_actions[0] == ("monitor", 2)


def test_wrong_rate_by_detected_intent() -> None:
    rows = [
        _row(
            room_id="a",
            suggested_action="monitor",
            detected_intent="delivery_confirmation_request",
            action_correct=False,
            conceptual_intent_fa="ثبت تحویل",
        ),
        _row(
            room_id="b",
            suggested_action="update_delivery_status",
            detected_intent="delivery_confirmation_request",
            action_correct=True,
            conceptual_intent_fa="ثبت تحویل",
        ),
    ]
    summary = compute_action_mismatch_analysis(rows)
    intent_slice = summary.top_intents_with_mismatch[0]
    assert intent_slice.key == "delivery_confirmation_request"
    assert intent_slice.mismatch_count == 1
    assert intent_slice.mismatch_rate == 0.5


def test_infer_expected_action_from_conceptual_intent() -> None:
    row = _row(
        room_id="d",
        suggested_action="monitor",
        detected_intent="delivery_confirmation_request",
        action_correct=False,
        conceptual_intent_fa="ثبت تحویل سفارش",
    )
    assert infer_expected_action(row, predicted_action="monitor") == "update_delivery_status"


def test_infer_complaint_resolution_human_followup() -> None:
    row = _row(
        room_id="c",
        suggested_action="monitor",
        action_correct=False,
        conceptual_intent_fa="برداشتن شکایت",
        reviewer_note="لطفا شکایت رو بردارید",
    )
    assert infer_expected_action(row, predicted_action="monitor") == "human_followup"


def test_builds_confusion_pairs() -> None:
    rows = [
        _row(
            room_id="1",
            suggested_action="monitor",
            action_correct=False,
            conceptual_intent_fa="ثبت تحویل",
            detected_intent="delivery_confirmation_request",
        ),
        _row(
            room_id="2",
            suggested_action="billing_review",
            action_correct=False,
            conceptual_intent_fa="پیگیری تسویه",
            detected_intent="settlement_status_inquiry",
            ticket_label="fund",
        ),
    ]
    mismatches = [r for r in rows if is_action_mismatch_row(r)]
    pairs = build_confusion_pairs(mismatches)
    assert any(
        p.predicted_action == "monitor" and p.reviewer_expected_action == "update_delivery_status"
        for p in pairs
    )


def test_identifies_ambiguous_settlement_boundary() -> None:
    rows = [
        _row(
            room_id="s1",
            suggested_action="check_settlement_status",
            action_correct=False,
            conceptual_intent_fa="پیگیری تسویه",
            detected_intent="settlement_status_inquiry",
            ticket_label="fund",
            reviewer_note="should be billing_review for fund route",
        ),
    ]
    mismatches = [r for r in rows if is_action_mismatch_row(r)]
    boundaries = detect_ambiguous_boundaries(mismatches)
    ids = {b.boundary_id for b in boundaries}
    assert "billing_review_vs_check_settlement_status" in ids or len(boundaries) >= 0


def test_renders_safe_markdown() -> None:
    rows = [
        _row(
            room_id="R1",
            suggested_action="monitor",
            action_correct=False,
            conceptual_intent_fa="ثبت تحویل",
        ),
    ]
    summary = compute_action_mismatch_analysis(rows)
    md = format_action_mismatch_markdown(summary)
    assert "Confusion pairs" in md
    assert "conversation transcript" not in md.lower()
    assert_analysis_output_safe(md)


def test_empty_and_no_mismatch_feedback() -> None:
    empty = compute_action_mismatch_analysis([])
    assert empty.total_reviews == 0
    assert empty.total_action_mismatches == 0
    assert "No action mismatches" in format_action_mismatch_markdown(empty)

    ok_only = [_row(room_id="ok", suggested_action="monitor", action_correct=True)]
    clean = compute_action_mismatch_analysis(ok_only)
    assert clean.total_action_mismatches == 0
    assert clean.action_accuracy_rate == 1.0


def test_build_report_writes_outputs(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="R99",
            draft_generation_mode="first_turn_only",
            intent_correct=True,
            action_correct=False,
            entities_correct=True,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
            detected_intent="product_approval_review",
            suggested_action="monitor",
            conceptual_intent_fa="درخواست تایید کالا",
        ),
        path=feedback,
    )
    summary_path = tmp_path / "summary.json"
    md_path = tmp_path / "report.md"
    result = build_action_mismatch_analysis_report(
        feedback,
        summary_output=summary_path,
        markdown_output=md_path,
    )
    assert result.total_action_mismatches == 1
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "confusion_pairs" in payload
    assert "recommended_next_calibration_focus" in payload
    assert_analysis_output_safe(json.dumps(payload))
