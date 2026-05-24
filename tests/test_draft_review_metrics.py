"""Tests for draft review metrics aggregation and report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.draft_review_metrics import (
    assert_metrics_output_safe,
    build_draft_review_metrics_report,
    compute_draft_review_metrics,
    detect_failure_patterns,
    format_draft_review_metrics_markdown,
)
from app.operator_console.draft_review_feedback import (
    DraftReviewFeedback,
    append_draft_review_feedback,
    build_draft_review_feedback_record,
)


def _row(
    *,
    room_id: str,
    draft_usable: bool = True,
    intent_correct: bool = True,
    action_correct: bool = True,
    entities_applicable: bool = True,
    entities_correct: bool | None = True,
    too_verbose: bool = False,
    hallucination_detected: bool = False,
    unnecessary_followup_detected: bool = False,
    detected_intent: str | None = "settlement_status_inquiry",
    conceptual_intent_fa: str | None = "پیگیری تسویه",
    suggested_action: str | None = "check_settlement_status",
    ticket_label: str | None = "fund",
    reviewer_note: str | None = None,
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


def test_rates_calculation_three_reviews() -> None:
    rows = [
        _row(room_id="A", draft_usable=True),
        _row(
            room_id="B",
            draft_usable=False,
            intent_correct=False,
            action_correct=False,
            too_verbose=True,
        ),
        _row(room_id="C", hallucination_detected=True, entities_correct=False),
    ]
    summary = compute_draft_review_metrics(rows, source_feedback_path="test.jsonl")
    assert summary.total_reviews == 3
    assert summary.usable_rate == pytest.approx(2 / 3, rel=1e-3)
    assert summary.hallucination_rate == pytest.approx(1 / 3, rel=1e-3)
    assert summary.verbosity_rate == pytest.approx(1 / 3, rel=1e-3)
    assert summary.intent_accuracy_rate == pytest.approx(2 / 3, rel=1e-3)
    assert summary.action_accuracy_rate == pytest.approx(2 / 3, rel=1e-3)
    assert summary.entity_accuracy_rate == pytest.approx(2 / 3, rel=1e-3)


def test_entity_accuracy_excludes_not_applicable() -> None:
    rows = [
        _row(room_id="A", entities_applicable=False, entities_correct=None),
        _row(room_id="B", entities_applicable=True, entities_correct=True),
        _row(room_id="C", entities_applicable=True, entities_correct=False),
    ]
    summary = compute_draft_review_metrics(rows)
    assert summary.entity_applicable_count == 2
    assert summary.entity_not_applicable_count == 1
    assert summary.entity_accuracy_rate == pytest.approx(0.5, rel=1e-3)


def test_empty_feedback_handling() -> None:
    summary = compute_draft_review_metrics([], source_feedback_path="empty.jsonl")
    assert summary.total_reviews == 0
    assert summary.usable_rate == 0.0
    assert summary.most_common_failure_patterns == ()
    md = format_draft_review_metrics_markdown(summary)
    assert "No draft reviews" in md
    assert_metrics_output_safe(md)


def test_failure_pattern_grouping_and_note_heuristics() -> None:
    row = _row(
        room_id="X",
        action_correct=False,
        intent_correct=False,
        entities_correct=False,
        draft_usable=False,
        too_verbose=True,
        hallucination_detected=True,
        reviewer_note="سیاست لغو سفارش نامشخص بود",
    )
    patterns = detect_failure_patterns(row)
    assert "action_mismatch" in patterns
    assert "wrong_intent" in patterns
    assert "missing_entity" in patterns
    assert "verbose_draft" in patterns
    assert "hallucination" in patterns
    assert "not_usable" in patterns
    assert "policy_misunderstanding" in patterns

    summary = compute_draft_review_metrics([row])
    assert summary.most_common_failure_patterns[0][0] in patterns


def test_breakdown_by_intent_and_ticket_label() -> None:
    rows = [
        _row(room_id="1", detected_intent="order_status_review", ticket_label="support"),
        _row(
            room_id="2",
            detected_intent="order_status_review",
            intent_correct=False,
            ticket_label="support",
        ),
        _row(room_id="3", detected_intent="complaint_escalation", ticket_label="complaint"),
    ]
    summary = compute_draft_review_metrics(rows)
    assert summary.by_detected_intent["order_status_review"].count == 2
    assert summary.by_detected_intent["order_status_review"].intent_accuracy_rate == 0.5
    assert summary.by_ticket_label["support"].count == 2
    assert summary.by_ticket_label["complaint"].count == 1


def test_markdown_rendering_includes_weak_sections(tmp_path: Path) -> None:
    rows = [
        _row(room_id="1", intent_correct=False, detected_intent="weak_intent"),
        _row(room_id="2", action_correct=False, suggested_action="weak_action"),
    ]
    summary = compute_draft_review_metrics(rows)
    md = format_draft_review_metrics_markdown(summary)
    assert "Top weak intents" in md
    assert "Top weak suggested actions" in md
    assert "Hallucination observations" in md
    assert_metrics_output_safe(md)


def test_build_report_writes_outputs(tmp_path: Path) -> None:
    feedback = tmp_path / "draft_review_feedback.jsonl"
    summary_path = tmp_path / "summary.json"
    md_path = tmp_path / "report.md"
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="R1",
            draft_generation_mode="first_turn_only",
            intent_correct=True,
            action_correct=True,
            entities_correct=True,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
            detected_intent="general_vendor_support",
            ticket_label="complaint",
            reviewer_note="Usable with minor edits",
        ),
        path=feedback,
    )
    result = build_draft_review_metrics_report(
        feedback,
        summary_output=summary_path,
        markdown_output=md_path,
    )
    assert result.total_reviews == 1
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["total_reviews"] == 1
    assert payload["usable_rate"] == 1.0
    assert "most_common_reviewer_notes" in payload
    md_text = md_path.read_text(encoding="utf-8")
    assert_metrics_output_safe(json.dumps(payload))
    assert_metrics_output_safe(md_text)
    assert "Usable with minor edits" in md_text


def test_no_forbidden_fields_in_json_output(tmp_path: Path) -> None:
    feedback = tmp_path / "reviews.jsonl"
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="Z",
            draft_generation_mode="first_turn_only",
            intent_correct=False,
            action_correct=False,
            entities_correct=False,
            draft_usable=False,
            too_verbose=True,
            hallucination_detected=True,
            suggested_better_reply="Short alternative wording only",
        ),
        path=feedback,
    )
    summary_path = tmp_path / "out.json"
    build_draft_review_metrics_report(
        feedback,
        summary_output=summary_path,
        markdown_output=tmp_path / "out.md",
    )
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    forbidden = {
        "messages",
        "gold_reference_reply",
        "retrieved_context",
        "prompt",
        "draft_response",
        "suggested_better_reply",
    }
    assert forbidden.isdisjoint(payload.keys())
    dumped = json.dumps(payload)
    for token in ("conversation transcript", '"messages"', "draft_response"):
        assert token.lower() not in dumped.lower()


def test_unnecessary_followup_rate_in_summary() -> None:
    rows = [
        _row(room_id="1", unnecessary_followup_detected=True),
        _row(room_id="2", unnecessary_followup_detected=False),
    ]
    summary = compute_draft_review_metrics(rows)
    assert summary.unnecessary_followup_rate == 0.5


def test_complaint_number_note_theme_aggregation() -> None:
    rows = [
        _row(
            room_id="7743",
            detected_intent="complaint_escalation",
            reviewer_note="شکایت شماره اشتباه",
        ),
        _row(
            room_id="7743b",
            detected_intent="complaint_escalation",
            reviewer_note="شکایت شماره اشتباه",
        ),
    ]
    summary = compute_draft_review_metrics(rows)
    assert summary.most_common_reviewer_notes[0] == ("شکایت شماره اشتباه", 2)
