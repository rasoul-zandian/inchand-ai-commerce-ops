"""Tests for offline replay metrics dashboard builder."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_replay_metrics_dashboard import (
    assert_dashboard_output_safe,
    build_dashboard,
    compute_replay_dashboard_metrics,
    format_markdown_dashboard,
    load_replay_report_rows,
    main,
    metrics_to_json_dict,
)


def _sample_rows() -> list[dict[str, object]]:
    return [
        {
            "room_id": "ROOM_A",
            "ticket_label": "support",
            "assigned_department": "support",
            "review_priority": "LOW",
            "route_label": "general_vendor_support",
            "detected_intent": "general_vendor_support",
            "reviewer_role": "support_operator",
            "human_approval_required": True,
            "qa_passed": True,
            "qa_issue_count": 0,
            "qa_warning_count": 1,
            "errors": [],
        },
        {
            "room_id": "ROOM_B",
            "ticket_label": "fund",
            "assigned_department": "finance",
            "review_priority": "HIGH",
            "route_label": "billing_review",
            "detected_intent": "billing_discrepancy",
            "reviewer_role": "finance_operator",
            "human_approval_required": True,
            "qa_passed": False,
            "qa_issue_count": 2,
            "qa_warning_count": 0,
            "errors": [],
        },
        {
            "room_id": "ROOM_C",
            "ticket_label": "support",
            "assigned_department": "finance",
            "review_priority": "MEDIUM",
            "route_label": "billing_review",
            "detected_intent": "billing_discrepancy",
            "reviewer_role": "finance_operator",
            "human_approval_required": True,
            "qa_passed": True,
            "qa_issue_count": 0,
            "qa_warning_count": 0,
            "errors": [],
        },
        {
            "room_id": "ROOM_FAIL",
            "ticket_label": "complaint",
            "assigned_department": "complaint",
            "review_priority": "LOW",
            "route_label": "general_vendor_support",
            "detected_intent": "general_vendor_support",
            "reviewer_role": "complaint_operator",
            "human_approval_required": False,
            "qa_passed": None,
            "qa_issue_count": 0,
            "qa_warning_count": 0,
            "errors": ["workflow_error: mock failure"],
        },
    ]


def test_compute_counts_and_matrix() -> None:
    metrics = compute_replay_dashboard_metrics(_sample_rows())  # type: ignore[arg-type]
    assert metrics.total_rows == 4
    assert metrics.workflow_success_count == 3
    assert metrics.failed_replay_count == 1
    assert metrics.human_approval_required_count == 3
    assert metrics.ticket_label_counts["support"] == 2
    assert metrics.assigned_department_counts["finance"] == 2
    assert metrics.high_priority_count == 1
    assert metrics.medium_priority_count == 1
    assert metrics.low_priority_count == 2
    assert metrics.department_priority_matrix["finance"]["HIGH"] == 1
    assert metrics.department_priority_matrix["support"]["LOW"] == 1
    assert metrics.qa_attention_count == 2
    assert metrics.total_qa_issue_count == 2
    assert metrics.label_vs_department_mismatch_count == 1
    assert metrics.mismatch_rate == 0.25


def test_markdown_has_expected_sections() -> None:
    metrics = compute_replay_dashboard_metrics(_sample_rows())  # type: ignore[arg-type]
    md = format_markdown_dashboard(
        metrics,
        source_path="reports/sample.jsonl",
        generated_at="2026-05-16T12:00:00Z",
    )
    assert "# Replay Metrics Dashboard" in md
    assert "## Executive Summary" in md
    assert "## Distributions" in md
    assert "## QA Summary" in md
    assert "## Department × Priority Matrix" in md
    assert "## Mismatch Analysis" in md
    assert "ROOM_C" in md
    assert_dashboard_output_safe(md)


def test_json_output_works(tmp_path: Path) -> None:
    report = tmp_path / "report.jsonl"
    report.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in _sample_rows()) + "\n",
        encoding="utf-8",
    )
    md_out = tmp_path / "dash.md"
    json_out = tmp_path / "dash.json"
    build_dashboard(report, markdown_output=md_out, json_output=json_out)
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["total_rows"] == 4
    assert payload["mismatch_rate"] == 0.25
    assert "draft_response" not in json.dumps(payload)
    assert_dashboard_output_safe(json.dumps(payload))


def test_output_excludes_raw_and_secrets(tmp_path: Path) -> None:
    rows = _sample_rows()
    rows[0]["secret_probe"] = "should not appear"  # type: ignore[index]
    report = tmp_path / "report.jsonl"
    # Only write safe replay-shaped rows (no forbidden top-level keys in real reports)
    report.write_text(
        json.dumps(rows[0], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_out = tmp_path / "dash.md"
    build_dashboard(report, markdown_output=md_out)
    text = md_out.read_text(encoding="utf-8")
    assert "should not appear" not in text
    assert "draft_response" not in text
    assert "مبلغ" not in text


def test_forbidden_key_in_report_fails(tmp_path: Path) -> None:
    report = tmp_path / "bad.jsonl"
    report.write_text(
        json.dumps({"room_id": "R", "draft_response": "secret draft"}) + "\n",
        encoding="utf-8",
    )
    try:
        load_replay_report_rows(report)
        raise AssertionError("expected ValueError for forbidden key")
    except ValueError as exc:
        assert "forbidden key" in str(exc)
        assert "secret draft" not in str(exc)


def test_invalid_json_line_fails_clearly(tmp_path: Path) -> None:
    report = tmp_path / "bad.jsonl"
    report.write_text("{not json\n", encoding="utf-8")
    try:
        load_replay_report_rows(report)
        raise AssertionError("expected JSON error")
    except ValueError as exc:
        assert "line 1" in str(exc)
        assert "not json" not in str(exc).lower() or "JSON" in str(exc)


def test_cli_builds_markdown(tmp_path: Path) -> None:
    report = tmp_path / "report.jsonl"
    report.write_text(
        json.dumps(_sample_rows()[0], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_out = tmp_path / "out.md"
    code = main([str(report), "--output", str(md_out)])
    assert code == 0
    assert md_out.is_file()
    assert "Replay Metrics Dashboard" in md_out.read_text(encoding="utf-8")


def test_metrics_json_dict_roundtrip() -> None:
    metrics = compute_replay_dashboard_metrics(_sample_rows())  # type: ignore[arg-type]
    payload = metrics_to_json_dict(
        metrics,
        source_path="reports/x.jsonl",
        generated_at="2026-05-16T12:00:00Z",
    )
    assert payload["department_priority_matrix"]["finance"]["HIGH"] == 1
    assert len(payload["mismatch_examples"]) == 1
