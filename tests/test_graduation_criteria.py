"""Tests for agentic sandbox graduation criteria (governance reporting)."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.graduation_criteria import (
    GraduationInputReports,
    OverallGraduationStatus,
    assert_graduation_output_safe,
    build_graduation_summary,
    evaluate_graduation_criteria,
    render_graduation_markdown,
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _passing_reports() -> GraduationInputReports:
    return GraduationInputReports(
        readiness={
            "safety_passed_rate": 1.0,
            "human_review_ready_rate": 0.95,
            "execution_allowed_true_count": 0,
            "customer_send_allowed_true_count": 0,
        },
        knowledge_coverage={"coverage_rate": 0.85},
        preview_metrics={
            "preview_usefulness_rate": 0.9,
            "intent_accuracy_rate": 0.9,
            "action_accuracy_rate": 0.85,
            "human_review_readiness_accuracy_rate": 1.0,
            "safety_correctness_rate": 1.0,
        },
        consistency={
            "room_count": 10,
            "status_counts": {"consistent": 9, "explainable_difference": 1, "mismatch": 0},
        },
        draft_metrics={"hallucination_rate": 0.0, "verbosity_rate": 0.05},
    )


def test_fully_passing_metrics_ready_for_operator_assisted_phase() -> None:
    evaluation = evaluate_graduation_criteria(_passing_reports())
    assert (
        evaluation.overall_status == OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value
    )
    assert not evaluation.blocking_issues
    assert all(item.status == "pass" for item in evaluation.criteria_results)


def test_advisory_weakness_conditionally_ready() -> None:
    reports = _passing_reports()
    reports = GraduationInputReports(
        readiness=reports.readiness,
        knowledge_coverage={"coverage_rate": 0.85},
        preview_metrics={
            **reports.preview_metrics,  # type: ignore[arg-type]
            "preview_usefulness_rate": 0.9,
        },
        consistency=reports.consistency,
        draft_metrics={"hallucination_rate": 0.05, "verbosity_rate": 0.05},
    )
    evaluation = evaluate_graduation_criteria(reports)
    assert evaluation.overall_status == OverallGraduationStatus.CONDITIONALLY_READY.value
    assert not evaluation.blocking_issues
    assert evaluation.advisory_issues


def test_safety_failure_not_ready() -> None:
    reports = _passing_reports()
    reports = GraduationInputReports(
        readiness={
            "safety_passed_rate": 0.5,
            "human_review_ready_rate": 0.95,
            "execution_allowed_true_count": 1,
            "customer_send_allowed_true_count": 0,
        },
        knowledge_coverage=reports.knowledge_coverage,
        preview_metrics=reports.preview_metrics,
        consistency=reports.consistency,
        draft_metrics=reports.draft_metrics,
    )
    evaluation = evaluate_graduation_criteria(reports)
    assert evaluation.overall_status == OverallGraduationStatus.NOT_READY.value
    assert evaluation.blocking_issues


def test_action_mismatch_not_ready() -> None:
    reports = _passing_reports()
    preview = dict(reports.preview_metrics or {})
    preview["action_accuracy_rate"] = 0.5
    evaluation = evaluate_graduation_criteria(
        GraduationInputReports(
            readiness=reports.readiness,
            knowledge_coverage=reports.knowledge_coverage,
            preview_metrics=preview,
            consistency=reports.consistency,
            draft_metrics=reports.draft_metrics,
        ),
    )
    assert evaluation.overall_status == OverallGraduationStatus.NOT_READY.value
    assert any(
        item.criterion_name == "action_accuracy" and item.status == "fail"
        for item in evaluation.criteria_results
    )


def test_missing_optional_reports_handled_gracefully() -> None:
    reports = GraduationInputReports(
        readiness={
            "safety_passed_rate": 1.0,
            "human_review_ready_rate": 0.95,
            "execution_allowed_true_count": 0,
            "customer_send_allowed_true_count": 0,
        },
        knowledge_coverage={"coverage_rate": 0.85},
        preview_metrics={
            "preview_usefulness_rate": 0.9,
            "intent_accuracy_rate": 0.9,
            "action_accuracy_rate": 0.85,
            "human_review_readiness_accuracy_rate": 1.0,
        },
        consistency=None,
        draft_metrics=None,
    )
    evaluation = evaluate_graduation_criteria(reports)
    assert evaluation.overall_status in {item.value for item in OverallGraduationStatus}
    consistency = next(
        item
        for item in evaluation.criteria_results
        if item.criterion_name == "console_graph_consistency"
    )
    assert consistency.status == "warning"
    draft_h = next(
        item
        for item in evaluation.criteria_results
        if item.criterion_name == "draft_hallucination_rate"
    )
    assert draft_h.status == "warning"


def test_markdown_excludes_forbidden_content() -> None:
    summary = build_graduation_summary(_passing_reports())
    md = render_graduation_markdown(summary)
    assert_graduation_output_safe(md)
    assert "conversation transcript" not in md.lower()
    assert "gold_reference_reply" not in md.lower()


def test_build_from_files(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    knowledge = tmp_path / "knowledge.json"
    preview = tmp_path / "preview.json"
    _write_json(readiness, _passing_reports().readiness)  # type: ignore[arg-type]
    _write_json(knowledge, {"coverage_rate": 0.9})
    _write_json(preview, _passing_reports().preview_metrics)  # type: ignore[arg-type]
    from app.agentic_sandbox.graduation_criteria import (
        build_agentic_sandbox_graduation_report,
    )

    summary = build_agentic_sandbox_graduation_report(
        readiness_path=readiness,
        knowledge_path=knowledge,
        preview_metrics_path=preview,
        consistency_path=tmp_path / "missing.json",
        draft_metrics_path=tmp_path / "missing_draft.json",
        summary_output=tmp_path / "graduation.json",
        markdown_output=tmp_path / "graduation.md",
    )
    assert summary.overall_status == OverallGraduationStatus.CONDITIONALLY_READY.value
    assert (tmp_path / "graduation.md").is_file()
