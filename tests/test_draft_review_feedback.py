"""Tests for structured draft review feedback (local JSONL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.draft_review_metrics import compute_draft_review_metrics
from app.operator_console.draft_preview import DraftPreviewRecord
from app.operator_console.draft_review_feedback import (
    BETTER_REPLY_MAX_CHARS,
    ENTITY_REVIEW_EXTRACTED_FAIL,
    ENTITY_REVIEW_EXTRACTED_OK,
    ENTITY_REVIEW_NOT_APPLICABLE,
    REVIEWER_NOTE_MAX_CHARS,
    DraftReviewFeedback,
    append_draft_review_feedback,
    assert_reviewer_text_safe,
    build_draft_review_feedback_record,
    draft_review_badge_lines,
    load_draft_review_feedback_summary,
    map_entity_review_ui_choice,
)


def _preview(*, room_id: str = "ROOM_DR") -> DraftPreviewRecord:
    return DraftPreviewRecord(
        room_id=room_id,
        case_id=f"{room_id}__first_vendor_turn",
        draft_reply="برای بررسی به تیم مربوطه ارجاع شد.",
        detected_intent="settlement_status_inquiry",
        conceptual_intent_fa="پیگیری تسویه",
        suggested_action="check_settlement_status",
        draft_style="operational_short",
        draft_generated=True,
    )


def test_build_and_append_feedback(tmp_path: Path) -> None:
    path = tmp_path / "draft_review_feedback.jsonl"
    record = build_draft_review_feedback_record(
        room_id="ROOM_1",
        draft_generation_mode="first_turn_only",
        intent_correct=True,
        action_correct=True,
        entities_correct=True,
        draft_usable=True,
        too_verbose=False,
        hallucination_detected=False,
        preview=_preview(room_id="ROOM_1"),
        reviewer_note="Usable with minor edits",
    )
    append_draft_review_feedback(record, path=path)
    summary = load_draft_review_feedback_summary(path)
    assert summary.total_reviews == 1
    assert summary.usable_count == 1
    assert summary.usable_percent == 100.0
    assert summary.by_detected_intent.get("settlement_status_inquiry") == 1


def test_summary_aggregation_multiple_rows(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    base = dict(
        draft_generation_mode="first_turn_only",
        intent_correct=True,
        action_correct=True,
        entities_correct=True,
    )
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="A",
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
            detected_intent="order_status_review",
            suggested_action="check_order_status",
            **base,
        ),
        path=path,
    )
    append_draft_review_feedback(
        build_draft_review_feedback_record(
            room_id="B",
            draft_usable=False,
            too_verbose=True,
            hallucination_detected=True,
            detected_intent="general_vendor_support",
            suggested_action="monitor",
            **base,
        ),
        path=path,
    )
    summary = load_draft_review_feedback_summary(path)
    assert summary.total_reviews == 2
    assert summary.usable_count == 1
    assert summary.verbose_count == 1
    assert summary.hallucination_count == 1


def test_unsafe_reviewer_note_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        build_draft_review_feedback_record(
            room_id="R",
            draft_generation_mode="first_turn_only",
            intent_correct=True,
            action_correct=True,
            entities_correct=True,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
            reviewer_note='see "messages" in thread',
        )


def test_oversized_better_reply_truncated(tmp_path: Path) -> None:
    long_text = "ا" * (BETTER_REPLY_MAX_CHARS + 40)
    record = build_draft_review_feedback_record(
        room_id="R",
        draft_generation_mode="first_turn_only",
        intent_correct=True,
        action_correct=True,
        entities_correct=True,
        draft_usable=True,
        too_verbose=False,
        hallucination_detected=False,
        suggested_better_reply=long_text,
    )
    assert record["suggested_better_reply"] is not None
    assert len(record["suggested_better_reply"]) <= BETTER_REPLY_MAX_CHARS


def test_no_forbidden_keys_written(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    record = build_draft_review_feedback_record(
        room_id="Z",
        draft_generation_mode="first_turn_only",
        intent_correct=False,
        action_correct=False,
        entities_correct=False,
        draft_usable=False,
        too_verbose=True,
        hallucination_detected=True,
        preview=_preview(room_id="Z"),
    )
    append_draft_review_feedback(record, path=path)
    parsed = json.loads(path.read_text(encoding="utf-8").strip())
    forbidden = {
        "messages",
        "user_input",
        "gold_reference_reply",
        "retrieved_context",
        "prompt",
        "prompt_body",
        "draft_response",
    }
    assert forbidden.isdisjoint(parsed.keys())


def test_operator_review_form_serialization() -> None:
    record = build_draft_review_feedback_record(
        room_id="ROOM_FORM",
        draft_generation_mode="first_turn_only",
        intent_correct=True,
        action_correct=False,
        entities_correct=True,
        draft_usable=True,
        too_verbose=False,
        hallucination_detected=False,
        preview=_preview(room_id="ROOM_FORM"),
        reviewer_note="x" * (REVIEWER_NOTE_MAX_CHARS + 5),
    )
    assert record["room_id"] == "ROOM_FORM"
    assert record["source"] == "operator_console"
    assert record["persisted_to"] == "local_jsonl"
    assert record["intent_correct"] is True
    assert record["action_correct"] is False


def test_badge_lines_good_and_risk() -> None:
    good = DraftReviewFeedback(
        review_id="1",
        timestamp_utc="2026-01-01T00:00:00+00:00",
        reviewer_id="local_operator",
        room_id="R",
        case_id=None,
        draft_generation_mode="first_turn_only",
        draft_style="operational_short",
        conceptual_intent_fa=None,
        detected_intent=None,
        suggested_action=None,
        ticket_label=None,
        intent_correct=True,
        action_correct=True,
        entities_correct=True,
        draft_usable=True,
        too_verbose=False,
        hallucination_detected=False,
    )
    assert draft_review_badge_lines(good) == ["✅ good draft"]

    risky = DraftReviewFeedback(
        review_id="2",
        timestamp_utc="2026-01-01T00:00:00+00:00",
        reviewer_id="local_operator",
        room_id="R",
        case_id=None,
        draft_generation_mode="first_turn_only",
        draft_style=None,
        conceptual_intent_fa=None,
        detected_intent=None,
        suggested_action=None,
        ticket_label=None,
        intent_correct=False,
        action_correct=False,
        entities_correct=False,
        draft_usable=False,
        too_verbose=True,
        hallucination_detected=True,
    )
    badges = draft_review_badge_lines(risky)
    assert "⚠️ verbose" in badges
    assert "⚠️ hallucination risk" in badges


def test_assert_reviewer_text_safe_rejects_pii() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_reviewer_text_safe("call 09123456789", field_name="reviewer_note")


@pytest.mark.parametrize(
    ("choice", "expected_applicable", "expected_correct"),
    [
        (ENTITY_REVIEW_EXTRACTED_OK, True, True),
        (ENTITY_REVIEW_EXTRACTED_FAIL, True, False),
        (ENTITY_REVIEW_NOT_APPLICABLE, False, None),
    ],
)
def test_entity_review_ui_choice_maps_to_storage(
    choice: str,
    expected_applicable: bool,
    expected_correct: bool | None,
) -> None:
    applicable, correct = map_entity_review_ui_choice(choice)
    assert applicable is expected_applicable
    assert correct is expected_correct


def test_entity_review_ui_metrics_denominator_uses_applicable_only() -> None:
    rows = [
        DraftReviewFeedback(
            review_id="1",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            reviewer_id="local_operator",
            room_id="A",
            case_id=None,
            draft_generation_mode="first_turn_only",
            draft_style=None,
            conceptual_intent_fa=None,
            detected_intent=None,
            suggested_action=None,
            intent_correct=True,
            action_correct=True,
            entities_applicable=False,
            entities_correct=None,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
        ),
        DraftReviewFeedback(
            review_id="2",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            reviewer_id="local_operator",
            room_id="B",
            case_id=None,
            draft_generation_mode="first_turn_only",
            draft_style=None,
            conceptual_intent_fa=None,
            detected_intent=None,
            suggested_action=None,
            intent_correct=True,
            action_correct=True,
            entities_applicable=True,
            entities_correct=True,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
        ),
        DraftReviewFeedback(
            review_id="3",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            reviewer_id="local_operator",
            room_id="C",
            case_id=None,
            draft_generation_mode="first_turn_only",
            draft_style=None,
            conceptual_intent_fa=None,
            detected_intent=None,
            suggested_action=None,
            intent_correct=True,
            action_correct=True,
            entities_applicable=True,
            entities_correct=False,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
        ),
    ]
    summary = compute_draft_review_metrics(rows)
    assert summary.entity_applicable_count == 2
    assert summary.entity_not_applicable_count == 1
    assert summary.entity_accuracy_rate == pytest.approx(0.5, rel=1e-3)


def test_entities_applicable_requires_correct_value() -> None:
    with pytest.raises(ValueError, match="entities_correct is required"):
        build_draft_review_feedback_record(
            room_id="R",
            draft_generation_mode="first_turn_only",
            intent_correct=True,
            action_correct=True,
            entities_applicable=True,
            entities_correct=None,
            draft_usable=True,
            too_verbose=False,
            hallucination_detected=False,
        )


def test_legacy_row_without_entities_applicable_parses() -> None:
    from app.operator_console.draft_review_feedback import parse_draft_review_feedback_row

    row = {
        "review_id": "legacy-1",
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "reviewer_id": "local_operator",
        "room_id": "LEG",
        "case_id": None,
        "draft_generation_mode": "first_turn_only",
        "draft_style": None,
        "conceptual_intent_fa": None,
        "detected_intent": None,
        "suggested_action": None,
        "ticket_label": None,
        "intent_correct": True,
        "action_correct": True,
        "entities_correct": False,
        "draft_usable": True,
        "too_verbose": False,
        "hallucination_detected": False,
        "unnecessary_followup_detected": False,
        "reviewer_note": None,
        "suggested_better_reply": None,
        "source": "operator_console",
        "persisted_to": "local_jsonl",
    }
    parsed = parse_draft_review_feedback_row(row)
    assert parsed is not None
    assert parsed.entities_applicable is True
    assert parsed.entities_correct is False
