"""Tests for operator-assisted mode pilot readiness reporting."""

from __future__ import annotations

import json
from pathlib import Path

from app.operator_console.assisted_mode_pilot_readiness import (
    AssistedPilotInputReports,
    OverallPilotReadinessStatus,
    assert_assisted_pilot_readiness_output_safe,
    build_assisted_mode_pilot_readiness_report,
    build_assisted_pilot_readiness_summary,
    evaluate_assisted_pilot_readiness,
    render_assisted_pilot_readiness_markdown,
)


def _passing_reports() -> AssistedPilotInputReports:
    return AssistedPilotInputReports(
        graduation={"overall_status": "ready_for_operator_assisted_phase"},
        readiness={
            "safety_passed_rate": 1.0,
            "human_review_ready_rate": 1.0,
            "execution_allowed_true_count": 0,
            "customer_send_allowed_true_count": 0,
            "total_runs": 20,
            "failed_runs": 0,
            "node_success_rates": {"generate_draft": 1.0, "safety_gate": 1.0},
        },
        knowledge_coverage={"coverage_rate": 0.85},
        assisted_metrics={
            "total_reviews": 8,
            "assisted_mode_usefulness_rate": 1.0,
            "overall_assisted_quality_rate": 0.99,
        },
        draft_metrics={"usable_rate": 0.9, "hallucination_rate": 0.0, "verbosity_rate": 0.05},
        consistency={
            "room_count": 10,
            "status_counts": {"consistent": 9, "explainable_difference": 1, "mismatch": 0},
        },
        draft_quality_slice={"weak_slices": []},
        action_mismatch={"total_action_mismatches": 0},
    )


def test_ready_metrics_ready_for_limited_internal_pilot() -> None:
    _, blocking, advisory, _, overall, _, _ = evaluate_assisted_pilot_readiness(
        _passing_reports(),
    )
    assert overall == OverallPilotReadinessStatus.READY_FOR_LIMITED_INTERNAL_PILOT.value
    assert not blocking
    assert not advisory


def test_advisory_issues_ready_with_guardrails() -> None:
    reports = _passing_reports()
    reports = AssistedPilotInputReports(
        graduation=reports.graduation,
        readiness=reports.readiness,
        knowledge_coverage=reports.knowledge_coverage,
        assisted_metrics=reports.assisted_metrics,
        draft_metrics={"usable_rate": 0.9, "hallucination_rate": 0.05, "verbosity_rate": 0.05},
        consistency=reports.consistency,
        draft_quality_slice=reports.draft_quality_slice,
        action_mismatch=reports.action_mismatch,
    )
    _, blocking, advisory, _, overall, _, _ = evaluate_assisted_pilot_readiness(reports)
    assert overall == OverallPilotReadinessStatus.READY_WITH_GUARDRAILS.value
    assert not blocking
    assert advisory


def test_safety_failure_not_ready_for_pilot() -> None:
    reports = _passing_reports()
    reports = AssistedPilotInputReports(
        graduation=reports.graduation,
        readiness={
            "safety_passed_rate": 0.5,
            "human_review_ready_rate": 0.5,
            "execution_allowed_true_count": 1,
            "customer_send_allowed_true_count": 0,
            "total_runs": 10,
            "failed_runs": 2,
            "node_success_rates": {"generate_draft": 0.5},
        },
        knowledge_coverage=reports.knowledge_coverage,
        assisted_metrics=reports.assisted_metrics,
        draft_metrics=reports.draft_metrics,
        consistency=reports.consistency,
        draft_quality_slice=reports.draft_quality_slice,
        action_mismatch=reports.action_mismatch,
    )
    _, blocking, _, _, overall, _, _ = evaluate_assisted_pilot_readiness(reports)
    assert overall == OverallPilotReadinessStatus.NOT_READY.value
    assert blocking


def test_missing_optional_reports_warning() -> None:
    reports = AssistedPilotInputReports(
        graduation={"overall_status": "ready_for_operator_assisted_phase"},
        readiness={
            "safety_passed_rate": 1.0,
            "human_review_ready_rate": 1.0,
            "execution_allowed_true_count": 0,
            "customer_send_allowed_true_count": 0,
            "total_runs": 10,
            "failed_runs": 0,
            "node_success_rates": {"generate_draft": 1.0},
        },
        knowledge_coverage={"coverage_rate": 0.85},
        assisted_metrics={
            "assisted_mode_usefulness_rate": 1.0,
            "overall_assisted_quality_rate": 1.0,
            "total_reviews": 5,
        },
        draft_metrics=None,
        consistency=None,
        draft_quality_slice=None,
        action_mismatch=None,
    )
    summary = build_assisted_pilot_readiness_summary(reports, source_reports={})
    assert any("optional report missing" in warning for warning in summary.missing_report_warnings)
    assert summary.overall_status in {
        OverallPilotReadinessStatus.READY_FOR_LIMITED_INTERNAL_PILOT.value,
        OverallPilotReadinessStatus.READY_WITH_GUARDRAILS.value,
    }


def test_markdown_excludes_forbidden_fields(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    summary = build_assisted_mode_pilot_readiness_report(
        graduation_path=tmp_path / "grad.json",
        readiness_path=tmp_path / "ready.json",
        knowledge_path=tmp_path / "know.json",
        assisted_metrics_path=tmp_path / "assisted.json",
        draft_metrics_path=tmp_path / "draft.json",
        consistency_path=tmp_path / "cons.json",
        summary_output=tmp_path / "pilot_summary.json",
        markdown_output=tmp_path / "pilot_report.md",
    )
    markdown = render_assisted_pilot_readiness_markdown(summary)
    lowered = markdown.lower()
    assert "draft_reply" not in lowered
    assert "conversation transcript" not in lowered
    assert "raw_prompt" not in lowered
    assert_assisted_pilot_readiness_output_safe(markdown)
    assert_assisted_pilot_readiness_output_safe(
        (tmp_path / "pilot_summary.json").read_text(encoding="utf-8"),
    )


def _write_passing_inputs(tmp_path: Path) -> None:
    reports = _passing_reports()
    (tmp_path / "grad.json").write_text(
        json.dumps(reports.graduation, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "ready.json").write_text(
        json.dumps(reports.readiness, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "know.json").write_text(
        json.dumps(reports.knowledge_coverage, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "assisted.json").write_text(
        json.dumps(reports.assisted_metrics, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "draft.json").write_text(
        json.dumps(reports.draft_metrics, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "cons.json").write_text(
        json.dumps(reports.consistency, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
