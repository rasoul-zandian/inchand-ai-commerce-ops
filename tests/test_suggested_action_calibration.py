"""Tests for suggested_action calibration from draft review feedback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.suggested_action_calibration import (
    assert_calibration_output_safe,
    build_suggested_action_calibration_report,
    compute_suggested_action_calibration,
    format_suggested_action_calibration_markdown,
    is_fallback_overuse_candidate,
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
    detected_intent: str,
    action_correct: bool = True,
    draft_usable: bool = True,
    conceptual_intent_fa: str | None = None,
    ticket_label: str | None = "support",
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
    )


def test_action_accuracy_aggregation() -> None:
    rows = [
        _row(room_id="1", suggested_action="monitor", detected_intent="general_vendor_support"),
        _row(
            room_id="2",
            suggested_action="check_order_status",
            detected_intent="order_status_review",
            action_correct=False,
        ),
        _row(
            room_id="3",
            suggested_action="monitor",
            detected_intent="order_status_review",
            action_correct=False,
        ),
    ]
    summary = compute_suggested_action_calibration(rows)
    assert summary.total_reviewed_actions == 3
    assert summary.action_accuracy_rate == pytest.approx(1 / 3, rel=1e-3)
    assert summary.monitor_usage_rate == pytest.approx(2 / 3, rel=1e-3)


def test_weakest_action_detection() -> None:
    rows = [
        _row(room_id="a", suggested_action="monitor", detected_intent="x", action_correct=True),
        _row(room_id="b", suggested_action="monitor", detected_intent="x", action_correct=False),
        _row(room_id="c", suggested_action="monitor", detected_intent="x", action_correct=False),
        _row(
            room_id="d",
            suggested_action="check_order_status",
            detected_intent="order_status_review",
            action_correct=True,
        ),
    ]
    summary = compute_suggested_action_calibration(rows)
    assert summary.weakest_actions[0].key == "monitor"
    assert summary.weakest_actions[0].accuracy_rate == 0.3333


def test_monitor_overuse_detection() -> None:
    row = _row(
        room_id="delivery",
        suggested_action="monitor",
        detected_intent="delivery_confirmation_request",
        conceptual_intent_fa="ثبت تحویل سفارش",
    )
    assert is_fallback_overuse_candidate(row) is True

    ok_row = _row(
        room_id="policy",
        suggested_action="answer_policy_question",
        detected_intent="prohibited_goods_question",
        conceptual_intent_fa="سوال مجاز بودن کالا",
    )
    assert is_fallback_overuse_candidate(ok_row) is False


def test_fallback_recommendation_generation() -> None:
    rows = [
        _row(
            room_id="d1",
            suggested_action="monitor",
            detected_intent="delivery_confirmation_request",
            action_correct=False,
            conceptual_intent_fa="ثبت تحویل",
        ),
        _row(
            room_id="d2",
            suggested_action="monitor",
            detected_intent="delivery_confirmation_request",
            action_correct=False,
        ),
    ]
    summary = compute_suggested_action_calibration(rows)
    adjustments = summary.suggested_mapping_adjustments
    assert any(
        a.detected_intent == "delivery_confirmation_request"
        and a.suggested_preferred_action == "update_delivery_status"
        for a in adjustments
    )


def test_operational_ticket_allows_followup_action() -> None:
    row = _row(
        room_id="op",
        suggested_action="human_followup",
        detected_intent="seller_operational_request",
        conceptual_intent_fa="لطفاً بررسی کنید",
        action_correct=True,
    )
    assert is_fallback_overuse_candidate(row) is False


def test_markdown_rendering() -> None:
    rows = [
        _row(
            room_id="1",
            suggested_action="monitor",
            detected_intent="product_approval_review",
            action_correct=False,
            conceptual_intent_fa="درخواست تایید کالا",
        ),
    ]
    summary = compute_suggested_action_calibration(rows)
    md = format_suggested_action_calibration_markdown(summary)
    assert "Weakest suggested actions" in md
    assert "Suggested calibration adjustments" in md
    assert_calibration_output_safe(md)


def test_empty_feedback_handling() -> None:
    summary = compute_suggested_action_calibration([])
    assert summary.total_reviewed_actions == 0
    assert summary.action_accuracy_rate == 0.0
    assert summary.fallback_overuse_count == 0
    md = format_suggested_action_calibration_markdown(summary)
    assert "No draft reviews" in md


def test_build_report_writes_outputs(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="R1",
            draft_generation_mode="first_turn_only",
            intent_correct=True,
            action_correct=False,
            entities_correct=True,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
            detected_intent="settlement_status_inquiry",
            suggested_action="monitor",
            conceptual_intent_fa="پیگیری تسویه",
        ),
        path=feedback,
    )
    summary_path = tmp_path / "summary.json"
    md_path = tmp_path / "report.md"
    result = build_suggested_action_calibration_report(
        feedback,
        summary_output=summary_path,
        markdown_output=md_path,
    )
    assert result.total_reviewed_actions == 1
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "suggested_mapping_adjustments" in payload
    assert_calibration_output_safe(json.dumps(payload))
