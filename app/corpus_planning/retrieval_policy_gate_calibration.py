"""Synthetic policy gate calibration (no pgvector, OpenAI, or LangGraph)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.corpus_planning.retrieval_policy_gate import (
    RetrievalGateDecision,
    RetrievalPolicyGateInput,
    RetrievalPolicyGateResult,
    RetrievalScenario,
    evaluate_retrieval_policy_gate,
)
from app.corpus_planning.retrieval_tool_models import RetrievalToolMetadataFilter
from app.corpus_planning.retrieval_tool_validation import validate_allowed_metadata_filter

_FORBIDDEN_OUTPUT_TOKENS = (
    "sk-",
    "BEGIN PRIVATE KEY",
    "OPENAI_API_KEY",
    "conversation_transcript",
)


class PolicyGateCalibrationCase(BaseModel):
    """One synthetic gate calibration fixture."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    input: dict[str, Any] | None = None
    metadata_filter_raw: dict[str, Any] | None = None
    expect_filter_validation_error: bool = False
    expected_decision: RetrievalGateDecision | None = None
    expected_scenario: RetrievalScenario | None = None
    expected_reason_contains: str | None = None
    expected_validation_error_contains: str | None = None


class PolicyGateCalibrationSuite(BaseModel):
    """Loaded calibration JSON file."""

    model_config = ConfigDict(extra="forbid")

    calibration_version: str
    description: str = ""
    cases: list[PolicyGateCalibrationCase] = Field(min_length=1)


@dataclass
class PolicyGateCalibrationCaseResult:
    case_id: str
    passed: bool
    expected_decision: str | None
    actual_decision: str | None
    expected_scenario: str | None
    actual_scenario: str | None
    failure_reasons: list[str] = field(default_factory=list)


@dataclass
class PolicyGateCalibrationReport:
    calibration_version: str
    source_path: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    decision_confusion_matrix: dict[str, dict[str, int]]
    scenario_counts: dict[str, int]
    results: list[PolicyGateCalibrationCaseResult] = field(default_factory=list)


def assert_safe_calibration_output(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise ValueError(f"calibration output must not contain forbidden token: {token}")


def load_policy_gate_calibration_cases(path: Path) -> PolicyGateCalibrationSuite:
    """Load synthetic calibration cases from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PolicyGateCalibrationSuite.model_validate(payload)


def _build_gate_input(case: PolicyGateCalibrationCase) -> RetrievalPolicyGateInput:
    if case.input is None:
        raise ValueError(
            f"case {case.case_id}: input is required unless expect_filter_validation_error"
        )
    raw = dict(case.input)
    metadata_raw = raw.pop("metadata_filter", None)
    metadata_filter: RetrievalToolMetadataFilter | None = None
    if metadata_raw is not None:
        metadata_filter = validate_allowed_metadata_filter(metadata_raw)
    return RetrievalPolicyGateInput.model_validate(
        {**raw, "metadata_filter": metadata_filter},
    )


def _reasons_joined(result: RetrievalPolicyGateResult) -> str:
    return " ".join(result.reasons).lower()


def score_policy_gate_calibration_case(
    case: PolicyGateCalibrationCase,
) -> PolicyGateCalibrationCaseResult:
    """Score one case against expected decision/scenario/reasons."""
    failure_reasons: list[str] = []

    if case.expect_filter_validation_error:
        if case.metadata_filter_raw is None:
            return PolicyGateCalibrationCaseResult(
                case_id=case.case_id,
                passed=False,
                expected_decision=None,
                actual_decision=None,
                expected_scenario=None,
                actual_scenario=None,
                failure_reasons=["metadata_filter_raw required for validation-error cases"],
            )
        try:
            validate_allowed_metadata_filter(case.metadata_filter_raw)
        except ValueError as exc:
            message = str(exc).lower()
            expected = (case.expected_validation_error_contains or "forbidden").lower()
            if expected not in message:
                failure_reasons.append(
                    f"validation error expected to contain {expected!r}, got {exc!s}",
                )
            return PolicyGateCalibrationCaseResult(
                case_id=case.case_id,
                passed=not failure_reasons,
                expected_decision="validation_error",
                actual_decision="validation_error",
                expected_scenario=None,
                actual_scenario=None,
                failure_reasons=failure_reasons,
            )
        return PolicyGateCalibrationCaseResult(
            case_id=case.case_id,
            passed=False,
            expected_decision="validation_error",
            actual_decision=None,
            expected_scenario=None,
            actual_scenario=None,
            failure_reasons=["expected metadata_filter validation to fail"],
        )

    try:
        gate_input = _build_gate_input(case)
    except (ValueError, ValidationError) as exc:
        return PolicyGateCalibrationCaseResult(
            case_id=case.case_id,
            passed=False,
            expected_decision=case.expected_decision.value if case.expected_decision else None,
            actual_decision=None,
            expected_scenario=case.expected_scenario.value if case.expected_scenario else None,
            actual_scenario=None,
            failure_reasons=[f"input_build_error: {exc}"],
        )

    result = evaluate_retrieval_policy_gate(gate_input)
    expected_decision = case.expected_decision
    expected_scenario = case.expected_scenario

    if expected_decision is not None and result.decision != expected_decision:
        failure_reasons.append(
            f"decision: expected {expected_decision.value}, got {result.decision.value}",
        )
    if expected_scenario is not None and result.scenario != expected_scenario:
        failure_reasons.append(
            f"scenario: expected {expected_scenario.value}, got {result.scenario.value}",
        )
    if case.expected_reason_contains:
        needle = case.expected_reason_contains.lower()
        if needle not in _reasons_joined(result):
            failure_reasons.append(
                f"reasons missing expected substring {case.expected_reason_contains!r}",
            )
    if result.retrieval_activated:
        failure_reasons.append("retrieval_activated must be false")
    if not result.sandbox_only:
        failure_reasons.append("sandbox_only must be true")

    return PolicyGateCalibrationCaseResult(
        case_id=case.case_id,
        passed=not failure_reasons,
        expected_decision=expected_decision.value if expected_decision else None,
        actual_decision=result.decision.value,
        expected_scenario=expected_scenario.value if expected_scenario else None,
        actual_scenario=result.scenario.value,
        failure_reasons=failure_reasons,
    )


def run_policy_gate_calibration(
    suite: PolicyGateCalibrationSuite,
    *,
    source_path: str,
) -> PolicyGateCalibrationReport:
    """Run all calibration cases and aggregate metrics."""
    results = [score_policy_gate_calibration_case(case) for case in suite.cases]
    passed = sum(1 for item in results if item.passed)
    total = len(results)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    scenario_counts: Counter[str] = Counter()

    for item in results:
        expected = item.expected_decision or "(none)"
        actual = item.actual_decision or "(none)"
        confusion[expected][actual] += 1
        if item.actual_scenario:
            scenario_counts[item.actual_scenario] += 1

    matrix = {row: dict(counts) for row, counts in sorted(confusion.items())}
    return PolicyGateCalibrationReport(
        calibration_version=suite.calibration_version,
        source_path=source_path,
        total_cases=total,
        passed_cases=passed,
        failed_cases=total - passed,
        pass_rate=(passed / total) if total else 0.0,
        decision_confusion_matrix=matrix,
        scenario_counts=dict(scenario_counts),
        results=results,
    )


def calibration_report_to_dict(report: PolicyGateCalibrationReport) -> dict[str, Any]:
    return {
        "calibration_version": report.calibration_version,
        "source_path": report.source_path,
        "total_cases": report.total_cases,
        "passed_cases": report.passed_cases,
        "failed_cases": report.failed_cases,
        "pass_rate": report.pass_rate,
        "decision_confusion_matrix": report.decision_confusion_matrix,
        "scenario_counts": report.scenario_counts,
        "results": [
            {
                "case_id": item.case_id,
                "passed": item.passed,
                "expected_decision": item.expected_decision,
                "actual_decision": item.actual_decision,
                "expected_scenario": item.expected_scenario,
                "actual_scenario": item.actual_scenario,
                "failure_reasons": item.failure_reasons,
            }
            for item in report.results
        ],
    }


def format_calibration_markdown(report: PolicyGateCalibrationReport) -> str:
    lines = [
        "# Retrieval Policy Gate Calibration Report",
        "",
        f"**Calibration version:** {report.calibration_version}  ",
        f"**Source:** `{report.source_path}`  ",
        "**Scope:** Synthetic edge-case fixtures only; no pgvector, OpenAI, or LangGraph.",
        "",
        "## Summary",
        "",
        f"- **total_cases:** {report.total_cases}",
        f"- **passed_cases:** {report.passed_cases}",
        f"- **failed_cases:** {report.failed_cases}",
        f"- **pass_rate:** {report.pass_rate:.4f}",
        "",
        "## Decision confusion matrix (expected × actual)",
        "",
    ]
    actual_cols = sorted(
        {col for row in report.decision_confusion_matrix.values() for col in row},
    )
    if not actual_cols:
        lines.append("*(no data)*")
    else:
        header = "| Expected \\ Actual | " + " | ".join(actual_cols) + " |"
        sep = "|-------------------|" + "|".join("------:" for _ in actual_cols) + "|"
        lines.extend([header, sep])
        for expected, counts in sorted(report.decision_confusion_matrix.items()):
            cells = " | ".join(str(counts.get(col, 0)) for col in actual_cols)
            lines.append(f"| {expected} | {cells} |")

    lines.extend(
        ["", "## Scenario counts (actual)", "", "| Scenario | Count |", "|----------|------:|"]
    )
    for scenario, count in sorted(report.scenario_counts.items()):
        lines.append(f"| {scenario} | {count} |")

    failures = [item for item in report.results if not item.passed]
    lines.extend(["", "## Failed cases", ""])
    if not failures:
        lines.append("*(none)*")
    else:
        for item in failures:
            lines.append(
                f"- `{item.case_id}`: expected={item.expected_decision} "
                f"actual={item.actual_decision}; {item.failure_reasons}",
            )

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Calibration does not execute retrieval or call pgvector/OpenAI.",
            "- `retrieval_activated` remains false on all gate results.",
            "- This report does not approve non-shadow retrieval consumption.",
            "",
        ]
    )
    return "\n".join(lines)


def write_policy_gate_calibration_report(
    report: PolicyGateCalibrationReport,
    *,
    json_output: Path,
    markdown_output: Path,
) -> None:
    """Write safe JSON and Markdown calibration reports."""
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    payload = calibration_report_to_dict(report)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    assert_safe_calibration_output(json_text)
    json_output.write_text(json_text, encoding="utf-8")

    markdown = format_calibration_markdown(report)
    assert_safe_calibration_output(markdown)
    markdown_output.write_text(markdown, encoding="utf-8")
