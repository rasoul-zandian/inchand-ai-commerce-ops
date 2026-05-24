"""Tests for agentic sandbox preview review feedback (local JSONL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    REVIEWER_NOTE_MAX_CHARS,
    append_agentic_preview_review_feedback,
    assert_preview_review_record_safe,
    assert_preview_review_text_safe,
    build_agentic_preview_review_record,
    load_agentic_preview_review_rows,
    load_agentic_preview_review_summary,
)


def _base_record(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "room_id": "7743",
        "graph_status_correct": True,
        "intent_correct": True,
        "action_correct": True,
        "actionability_correct": True,
        "entity_extraction_correct": True,
        "knowledge_hints_helpful": False,
        "safety_correct": True,
        "ready_for_human_review_correct": True,
        "draft_length_reasonable": True,
        "overall_preview_useful": True,
    }
    data.update(overrides)
    return build_agentic_preview_review_record(**data)  # type: ignore[arg-type]


def test_append_feedback_row(tmp_path: Path) -> None:
    path = tmp_path / "preview_reviews.jsonl"
    record = _base_record(room_id="7743", reviewer_notes="Graph looked right")
    append_agentic_preview_review_feedback(record, path=path)
    rows = load_agentic_preview_review_rows(path)
    assert len(rows) == 1
    assert rows[0].room_id == "7743"
    assert rows[0].overall_preview_useful is True


def test_summary_aggregation(tmp_path: Path) -> None:
    path = tmp_path / "preview_reviews.jsonl"
    append_agentic_preview_review_feedback(
        _base_record(
            room_id="A",
            intent_correct=True,
            action_correct=True,
            overall_preview_useful=True,
        ),
        path=path,
    )
    append_agentic_preview_review_feedback(
        _base_record(
            room_id="B",
            intent_correct=False,
            action_correct=False,
            knowledge_hints_helpful=True,
            overall_preview_useful=False,
        ),
        path=path,
    )
    summary = load_agentic_preview_review_summary(path)
    assert summary.total_reviews == 2
    assert summary.preview_usefulness_percent == 50.0
    assert summary.intent_correctness_percent == 50.0
    assert summary.action_correctness_percent == 50.0
    assert summary.knowledge_helpfulness_percent == 50.0


def test_unsafe_notes_blocked() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        build_agentic_preview_review_record(
            room_id="7743",
            graph_status_correct=True,
            intent_correct=True,
            action_correct=True,
            actionability_correct=True,
            entity_extraction_correct=True,
            knowledge_hints_helpful=True,
            safety_correct=True,
            ready_for_human_review_correct=True,
            draft_length_reasonable=True,
            overall_preview_useful=True,
            reviewer_notes='see "messages" in thread',
        )


def test_no_forbidden_fields_persisted(tmp_path: Path) -> None:
    path = tmp_path / "preview_reviews.jsonl"
    record = _base_record(reviewer_notes="ok")
    append_agentic_preview_review_feedback(record, path=path)
    line = path.read_text(encoding="utf-8").strip()
    lowered = line.lower()
    assert "draft_reply" not in lowered
    assert "transcript" not in lowered
    assert_preview_review_record_safe(line)
    assert set(json.loads(line).keys()) <= {
        "review_id",
        "room_id",
        "review_timestamp_utc",
        "graph_status_correct",
        "intent_correct",
        "action_correct",
        "actionability_correct",
        "entity_extraction_correct",
        "knowledge_hints_helpful",
        "safety_correct",
        "ready_for_human_review_correct",
        "draft_length_reasonable",
        "overall_preview_useful",
        "unnecessary_additional_details_requested",
        "reviewer_notes",
        "source",
        "persisted_to",
    }


def test_sidebar_metrics_computed_from_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    summary = load_agentic_preview_review_summary(path)
    assert summary.total_reviews == 0
    assert summary.preview_usefulness_percent == 0.0


def test_legacy_empty_file_handling(tmp_path: Path) -> None:
    path = tmp_path / "preview_reviews.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    assert load_agentic_preview_review_rows(path) == []
    summary = load_agentic_preview_review_summary(path)
    assert summary.total_reviews == 0


def test_oversized_note_truncated(tmp_path: Path) -> None:
    long_note = "ن" * (REVIEWER_NOTE_MAX_CHARS + 50)
    record = _base_record(reviewer_notes=long_note)
    assert len(record["reviewer_notes"]) <= REVIEWER_NOTE_MAX_CHARS


def test_default_path_constant() -> None:
    assert str(DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH).endswith(
        "agentic_preview_review_feedback.jsonl",
    )


def test_assert_preview_review_text_safe_pii() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_preview_review_text_safe("call me at 09121234567")
