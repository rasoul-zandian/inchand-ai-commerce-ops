"""Tests for operator-assisted review metrics reporting."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import build_agentic_preview_review_record
from app.operator_console.agentic_assisted_review_metrics import (
    OperatorAssistedReviewRecord,
    assert_operator_assisted_review_metrics_output_safe,
    build_operator_assisted_review_metrics_report,
    detect_weakest_assisted_dimensions,
    load_operator_assisted_review_records,
    render_operator_assisted_review_metrics_markdown,
)
from app.operator_console.i18n import LANG_EN, LANG_FA, apply_console_direction_css


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
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_metrics_report_builds_correctly(tmp_path: Path) -> None:
    preview = tmp_path / "preview.jsonl"
    _write_jsonl(
        preview,
        [
            _record(room_id="A", overall_preview_useful=True),
            _record(
                room_id="B",
                overall_preview_useful=False,
                intent_correct=False,
                draft_length_reasonable=False,
            ),
        ],
    )
    summary = build_operator_assisted_review_metrics_report(
        preview,
        assisted_extension_path=None,
        summary_output=tmp_path / "summary.json",
        markdown_output=tmp_path / "report.md",
    )
    assert summary.total_reviews == 2
    assert summary.assisted_mode_usefulness_rate == 0.5
    assert summary.draft_helpfulness_rate == 0.5
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "report.md").is_file()


def test_report_excludes_forbidden_content(tmp_path: Path) -> None:
    preview = tmp_path / "preview.jsonl"
    _write_jsonl(
        preview,
        [
            _record(
                room_id="7743",
                reviewer_notes="mapping looked off",
                overall_preview_useful=False,
            ),
        ],
    )
    summary = build_operator_assisted_review_metrics_report(
        preview,
        assisted_extension_path=None,
        summary_output=tmp_path / "summary.json",
        markdown_output=tmp_path / "report.md",
    )
    markdown = render_operator_assisted_review_metrics_markdown(summary)
    lowered = markdown.lower()
    assert "draft_reply" not in lowered
    assert "conversation transcript" not in lowered
    assert "raw_prompt" not in lowered
    assert "mapping looked off" not in markdown
    assert_operator_assisted_review_metrics_output_safe(markdown)
    assert_operator_assisted_review_metrics_output_safe(
        (tmp_path / "summary.json").read_text(encoding="utf-8"),
    )


def test_assisted_extension_overrides_preview_fields(tmp_path: Path) -> None:
    preview = tmp_path / "preview.jsonl"
    assisted = tmp_path / "assisted.jsonl"
    row = _record(room_id="7743", overall_preview_useful=False, draft_length_reasonable=False)
    _write_jsonl(preview, [row])
    extended = dict(row)
    extended["assisted_mode_useful"] = True
    extended["draft_helpful"] = True
    extended["operator_trust_confident"] = True
    extended["review_context"] = "operator_assisted"
    _write_jsonl(assisted, [extended])

    records, skipped = load_operator_assisted_review_records(
        preview,
        assisted_extension_path=assisted,
    )
    assert skipped == 0
    assert len(records) == 1
    assert records[0].resolved_assisted_mode_useful is True
    assert records[0].resolved_draft_helpful is True
    assert records[0].resolved_operator_trust is True


def test_weakest_dimensions_detection() -> None:
    from app.agentic_sandbox.preview_review_feedback import parse_agentic_preview_review_row

    parsed_a = parse_agentic_preview_review_row(
        _record(room_id="1", intent_correct=False, entity_extraction_correct=False),
    )
    parsed_b = parse_agentic_preview_review_row(
        _record(room_id="2", intent_correct=False, entity_extraction_correct=False),
    )
    assert parsed_a is not None and parsed_b is not None
    rows = [
        OperatorAssistedReviewRecord(review=parsed_a),
        OperatorAssistedReviewRecord(review=parsed_b),
    ]
    weakest = detect_weakest_assisted_dimensions(rows)
    assert "intent" in weakest


def test_fa_css_flips_sidebar_right() -> None:
    css = apply_console_direction_css(LANG_FA)
    assert "right: 0" in css
    assert "left: auto" in css
    assert "direction: rtl" in css


def test_en_css_does_not_flip_sidebar() -> None:
    assert apply_console_direction_css(LANG_EN) == ""


def test_fa_css_keeps_code_blocks_ltr() -> None:
    css = apply_console_direction_css(LANG_FA)
    assert "stCodeBlock" in css or "pre," in css
    assert "direction: ltr !important" in css
