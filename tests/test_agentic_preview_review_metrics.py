"""Tests for agentic sandbox preview review metrics reporting."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import (
    build_agentic_preview_review_record,
    parse_agentic_preview_review_row,
)
from app.agentic_sandbox.preview_review_metrics import (
    PreviewReviewRecordWithContext,
    assert_preview_review_metrics_output_safe,
    build_agentic_preview_review_metrics_report,
    detect_weakest_graph_dimensions,
    load_preview_review_records_with_context,
    render_preview_review_metrics_markdown,
    summarize_preview_review_metrics,
)


def _record(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "room_id": "7743",
        "graph_status_correct": True,
        "intent_correct": True,
        "action_correct": True,
        "actionability_correct": True,
        "entity_extraction_correct": True,
        "knowledge_hints_helpful": True,
        "safety_correct": True,
        "ready_for_human_review_correct": True,
        "draft_length_reasonable": True,
        "overall_preview_useful": True,
    }
    data.update(overrides)
    return build_agentic_preview_review_record(**data)  # type: ignore[arg-type]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_empty_feedback_file_handling(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    records, skipped = load_preview_review_records_with_context(feedback)
    assert records == []
    assert skipped == 0
    summary = summarize_preview_review_metrics(records, source_feedback_path=str(feedback))
    assert summary.total_reviews == 0
    assert summary.preview_usefulness_rate == 0.0


def test_rate_calculations(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_jsonl(
        feedback,
        [
            _record(room_id="A", overall_preview_useful=True, intent_correct=True),
            _record(
                room_id="B",
                overall_preview_useful=False,
                intent_correct=False,
                action_correct=False,
                knowledge_hints_helpful=False,
            ),
        ],
    )
    records, skipped = load_preview_review_records_with_context(feedback)
    assert skipped == 0
    summary = summarize_preview_review_metrics(records, source_feedback_path=str(feedback))
    assert summary.total_reviews == 2
    assert summary.preview_usefulness_rate == 0.5
    assert summary.intent_accuracy_rate == 0.5
    assert summary.action_accuracy_rate == 0.5
    assert summary.knowledge_helpfulness_rate == 0.5
    assert summary.wrong_intent_count == 1
    assert summary.wrong_action_count == 1


def test_weakest_dimension_detection() -> None:
    parsed_a = parse_agentic_preview_review_row(
        _record(room_id="1", intent_correct=False, entity_extraction_correct=False),
    )
    parsed_b = parse_agentic_preview_review_row(
        _record(room_id="2", intent_correct=False, entity_extraction_correct=False),
    )
    assert parsed_a is not None and parsed_b is not None
    rows = [
        PreviewReviewRecordWithContext(review=parsed_a),
        PreviewReviewRecordWithContext(review=parsed_b),
    ]
    weakest = detect_weakest_graph_dimensions(rows)
    assert weakest[0] in {"intent", "entity_extraction"}
    assert "intent" in weakest


def test_malformed_rows_skipped_safely(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    feedback.write_text(
        json.dumps(_record(room_id="OK"), ensure_ascii=False)
        + "\n"
        + "not-json\n"
        + json.dumps({"room_id": "missing-fields"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    records, skipped = load_preview_review_records_with_context(feedback)
    assert len(records) == 1
    assert skipped == 2


def test_markdown_excludes_forbidden_fields(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_jsonl(
        feedback,
        [
            _record(
                room_id="7743",
                reviewer_notes="intent mapping looked off",
                overall_preview_useful=False,
                intent_correct=False,
            ),
        ],
    )
    summary = build_agentic_preview_review_metrics_report(
        feedback,
        summary_output=tmp_path / "summary.json",
        markdown_output=tmp_path / "report.md",
    )
    markdown = render_preview_review_metrics_markdown(summary)
    lowered = markdown.lower()
    assert "draft_reply" not in lowered
    assert "conversation transcript" not in lowered
    assert "raw_prompt" not in lowered
    assert "retrieved_context" not in lowered
    assert '"messages"' not in lowered
    assert "intent mapping looked off" not in markdown
    assert "reviewer_notes" not in lowered
    assert_preview_review_metrics_output_safe(markdown)
    assert_preview_review_metrics_output_safe(
        (tmp_path / "summary.json").read_text(encoding="utf-8"),
    )


def test_notes_summarized_safely_without_raw_text(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_jsonl(
        feedback,
        [_record(room_id="1", reviewer_notes="graph nodes looked consistent")],
    )
    records, _ = load_preview_review_records_with_context(feedback)
    summary = summarize_preview_review_metrics(records, source_feedback_path=str(feedback))
    assert summary.reviews_with_notes_count == 1
    assert summary.operator_notes_summary is not None
    assert "graph nodes" not in (summary.operator_notes_summary or "")
    assert "omitted" in (summary.operator_notes_summary or "").lower()


def test_breakdown_by_intent_when_present(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    row = _record(room_id="1", intent_correct=False, overall_preview_useful=False)
    row["detected_intent"] = "complaint_escalation"
    _write_jsonl(feedback, [row])
    records, _ = load_preview_review_records_with_context(feedback)
    summary = summarize_preview_review_metrics(records, source_feedback_path=str(feedback))
    assert "complaint_escalation" in summary.by_detected_intent
    assert summary.by_detected_intent["complaint_escalation"]["wrong_intent_count"] == 1


def test_build_report_writes_outputs(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_jsonl(feedback, [_record(room_id="1")])
    summary_path = tmp_path / "summary.json"
    md_path = tmp_path / "report.md"
    summary = build_agentic_preview_review_metrics_report(
        feedback,
        summary_output=summary_path,
        markdown_output=md_path,
    )
    assert summary.total_reviews == 1
    assert summary_path.is_file()
    assert md_path.is_file()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["total_reviews"] == 1
