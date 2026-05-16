"""Tests for retrieval quality threshold gates (no DB, no OpenAI)."""

from __future__ import annotations

import pytest
from app.rag.evaluation import (
    RetrievalEvalReport,
    RetrievalEvalResult,
    RetrievalQualityThresholds,
    comparison_exit_code_for_quality_gates,
    evaluate_comparison_quality_gates,
    evaluate_report_quality_gates,
    format_quality_gate_lines,
    load_retrieval_quality_thresholds_from_env,
    quality_gates_passed,
    report_exit_code_for_quality_gates,
)
from scripts.compare_retrieval_backends import build_comparison_payload


def _result(
    case_id: str,
    *,
    passed: bool,
    recall: float = 1.0,
    mrr: float = 1.0,
) -> RetrievalEvalResult:
    return RetrievalEvalResult(
        case_id=case_id,
        query="q",
        passed=passed,
        retrieved_document_ids=["d1"] if passed else [],
        expected_document_ids=["d1"],
        matched_document_ids=["d1"] if passed else [],
        missing_document_ids=[] if passed else ["d1"],
        retrieved_source_types=["policy"],
        required_source_types=[],
        missing_source_types=[],
        top_k=5,
        recall_at_k=recall,
        hit_rate=1.0 if recall > 0 else 0.0,
        mrr=mrr,
        first_match_rank=1 if passed else None,
    )


def _report(
    *results: RetrievalEvalResult,
    pass_rate: float | None = None,
    near_miss_violation_count: int = 0,
) -> RetrievalEvalReport:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    failed = total - passed
    rate = pass_rate if pass_rate is not None else ((passed / total) if total else 0.0)
    return RetrievalEvalReport(
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        pass_rate=rate,
        mean_recall_at_k=sum(r.recall_at_k for r in results) / total if total else 0.0,
        mean_hit_rate=sum(r.hit_rate for r in results) / total if total else 0.0,
        mean_mrr=sum(r.mrr for r in results) / total if total else 0.0,
        near_miss_violation_count=near_miss_violation_count,
        results=list(results),
    )


def test_report_gate_fails_low_pass_rate() -> None:
    report = _report(_result("a", passed=False), pass_rate=0.0)
    thresholds = RetrievalQualityThresholds(enabled=True, min_pass_rate=1.0)
    checks = evaluate_report_quality_gates(report, thresholds)
    assert not quality_gates_passed(checks)
    assert report_exit_code_for_quality_gates(report, thresholds) == 1


def test_report_gate_passes_perfect_metrics() -> None:
    report = _report(_result("a", passed=True))
    thresholds = RetrievalQualityThresholds(enabled=True)
    checks = evaluate_report_quality_gates(report, thresholds)
    assert quality_gates_passed(checks)
    assert report_exit_code_for_quality_gates(report, thresholds) == 0


def test_comparison_gate_fails_regression() -> None:
    baseline = _report(_result("a", passed=True))
    pgvector = _report(_result("a", passed=True, mrr=0.5))
    payload = build_comparison_payload(baseline, pgvector)
    thresholds = RetrievalQualityThresholds(enabled=True, max_mean_mrr_regression=0.0)
    checks = evaluate_comparison_quality_gates(payload, thresholds)
    assert not quality_gates_passed(checks)
    assert comparison_exit_code_for_quality_gates(payload, thresholds) == 1


def test_comparison_gate_fails_different_cases() -> None:
    baseline = _report(_result("a", passed=True, recall=1.0))
    pgvector = _report(_result("a", passed=True, recall=0.5))
    payload = build_comparison_payload(baseline, pgvector)
    thresholds = RetrievalQualityThresholds(
        enabled=True,
        require_matching_case_results=True,
        max_mean_recall_at_k_regression=1.0,
    )
    checks = evaluate_comparison_quality_gates(payload, thresholds)
    assert not quality_gates_passed(checks)


def test_comparison_gate_passes_matching_backends() -> None:
    baseline = _report(_result("a", passed=True))
    pgvector = _report(_result("a", passed=True))
    payload = build_comparison_payload(baseline, pgvector)
    thresholds = RetrievalQualityThresholds(enabled=True)
    assert comparison_exit_code_for_quality_gates(payload, thresholds) == 0


def test_gates_disabled_uses_legacy_pass_rate_only() -> None:
    report = _report(_result("a", passed=False), pass_rate=0.5)
    thresholds = RetrievalQualityThresholds(enabled=False)
    assert report_exit_code_for_quality_gates(report, thresholds) == 1

    baseline = _report(_result("a", passed=True))
    pgvector = _report(_result("a", passed=True))
    payload = build_comparison_payload(baseline, pgvector)
    assert comparison_exit_code_for_quality_gates(payload, thresholds) == 0


def test_format_quality_gate_lines_no_secrets() -> None:
    report = _report(_result("a", passed=False), pass_rate=0.0)
    checks = evaluate_report_quality_gates(report, RetrievalQualityThresholds(enabled=True))
    text = "\n".join(format_quality_gate_lines(checks))
    assert "quality gates: failed" in text
    assert "min_pass_rate" in text
    assert "postgresql" not in text.lower()


def test_report_near_miss_gate_passes_at_threshold() -> None:
    report = _report(_result("a", passed=True), near_miss_violation_count=0)
    thresholds = RetrievalQualityThresholds(
        enabled=True,
        max_near_miss_violations=0,
        min_pass_rate=0.0,
        min_mean_recall_at_k=0.0,
        min_mean_hit_rate=0.0,
        min_mean_mrr=0.0,
    )
    checks = evaluate_report_quality_gates(report, thresholds)
    near_miss_checks = [c for c in checks if c.name == "max_near_miss_violations"]
    assert len(near_miss_checks) == 1
    assert near_miss_checks[0].passed is True


def test_report_near_miss_gate_fails_when_exceeding_threshold() -> None:
    report = _report(_result("a", passed=True), near_miss_violation_count=2)
    thresholds = RetrievalQualityThresholds(
        enabled=True,
        max_near_miss_violations=0,
        min_pass_rate=0.0,
        min_mean_recall_at_k=0.0,
        min_mean_hit_rate=0.0,
        min_mean_mrr=0.0,
    )
    checks = evaluate_report_quality_gates(report, thresholds)
    near_miss = next(c for c in checks if c.name == "max_near_miss_violations")
    assert near_miss.passed is False
    assert "near_miss_violation_count 2 exceeds max_near_miss_violations 0" in near_miss.detail
    assert report_exit_code_for_quality_gates(report, thresholds) == 1


def test_comparison_near_miss_regression_passes_at_threshold() -> None:
    baseline = _report(_result("a", passed=True), near_miss_violation_count=1)
    pgvector = _report(_result("a", passed=True), near_miss_violation_count=1)
    payload = build_comparison_payload(baseline, pgvector)
    thresholds = RetrievalQualityThresholds(
        enabled=True,
        max_near_miss_violation_regression=0,
        min_pass_rate=0.0,
        min_mean_recall_at_k=0.0,
        min_mean_hit_rate=0.0,
        min_mean_mrr=0.0,
        require_matching_case_results=False,
    )
    checks = evaluate_comparison_quality_gates(payload, thresholds)
    reg = next(c for c in checks if c.name == "max_near_miss_violation_regression")
    assert reg.passed is True


def test_comparison_near_miss_regression_fails_when_exceeding_threshold() -> None:
    baseline = _report(_result("a", passed=True), near_miss_violation_count=0)
    pgvector = _report(_result("a", passed=True), near_miss_violation_count=2)
    payload = build_comparison_payload(baseline, pgvector)
    thresholds = RetrievalQualityThresholds(
        enabled=True,
        max_near_miss_violation_regression=0,
        min_pass_rate=0.0,
        min_mean_recall_at_k=0.0,
        min_mean_hit_rate=0.0,
        min_mean_mrr=0.0,
        require_matching_case_results=False,
    )
    checks = evaluate_comparison_quality_gates(payload, thresholds)
    reg = next(c for c in checks if c.name == "max_near_miss_violation_regression")
    assert reg.passed is False
    assert (
        "near_miss_violation_count regression 2 exceeds max_near_miss_violation_regression 0"
        in reg.detail
    )
    assert comparison_exit_code_for_quality_gates(payload, thresholds) == 1


def test_env_near_miss_threshold_accepts_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS", "0")
    monkeypatch.setenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION", "0")
    thresholds = load_retrieval_quality_thresholds_from_env()
    assert thresholds.max_near_miss_violations == 0
    assert thresholds.max_near_miss_violation_regression == 0


def test_env_near_miss_threshold_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS", raising=False)
    monkeypatch.delenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION", raising=False)
    thresholds = load_retrieval_quality_thresholds_from_env()
    assert thresholds.max_near_miss_violations is None
    assert thresholds.max_near_miss_violation_regression is None


def test_env_near_miss_threshold_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS", "-1")
    with pytest.raises(ValueError, match="RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS"):
        load_retrieval_quality_thresholds_from_env()


def test_env_near_miss_threshold_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION", "bad")
    with pytest.raises(ValueError, match="RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION"):
        load_retrieval_quality_thresholds_from_env()
