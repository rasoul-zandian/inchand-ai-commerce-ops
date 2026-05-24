"""Pilot readiness assessment for operator-assisted agentic mode (governance only)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.agentic_sandbox.graduation_criteria import (
    DEFAULT_GRADUATION_SUMMARY_PATH,
    OverallGraduationStatus,
    load_summary_json,
)
from app.agentic_sandbox.report_paths import (
    DEFAULT_COVERAGE_SUMMARY_PATH,
    DEFAULT_READINESS_SUMMARY_PATH,
)
from app.operator_console.agentic_assisted_review_metrics import (
    DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
)
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS

DEFAULT_PILOT_READINESS_SUMMARY_PATH = Path(
    "reports/assisted_mode_pilot_readiness_summary.json",
)
DEFAULT_PILOT_READINESS_REPORT_PATH = Path(
    "reports/assisted_mode_pilot_readiness_report.md",
)
DEFAULT_DRAFT_METRICS_SUMMARY_PATH = Path("reports/draft_review_metrics_summary.json")
DEFAULT_CONSISTENCY_SUMMARY_PATH = Path("reports/console_graph_consistency_summary.json")
DEFAULT_DRAFT_QUALITY_SLICE_SUMMARY_PATH = Path(
    "reports/draft_quality_slice_analysis_summary.json",
)
DEFAULT_ACTION_MISMATCH_SUMMARY_PATH = Path("reports/action_mismatch_analysis_summary.json")

SAFETY_PASSED_RATE_MIN = 0.99
NODE_SUCCESS_MIN = 0.95
GRAPH_ERROR_RATE_MAX = 0.05
POLICY_COVERAGE_MIN = 0.80
ASSISTED_USEFULNESS_MIN = 0.85
ASSISTED_QUALITY_MIN = 0.85
DRAFT_USABLE_RATE_MIN = 0.85
HUMAN_REVIEW_READY_RATE_MIN = 0.99
CONSISTENCY_MISMATCH_WARN = 0.10
CONSISTENCY_MISMATCH_FAIL = 0.25
VERBOSITY_RATE_WARN = 0.20
MIN_ASSISTED_REVIEWS_ADVISORY = 3

_GRADUATION_READY_TARGET = (
    f"overall_status == {OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value}"
)

_CRITICAL_CRITERIA = frozenset(
    {
        "execution_disabled",
        "customer_send_disabled",
        "safety_passed_rate",
        "graduation_ready",
        "graph_error_rate",
        "graph_node_success",
    },
)

_PILOT_SCOPE: tuple[str, ...] = (
    "First-turn seller-initiated tickets only (DRAFT_GENERATION_MODE=first_turn_only).",
    "Internal operators only; no vendor-facing automation.",
    "Mock or OpenAI provider explicitly selected per run (no implicit production graph).",
    "No customer send button; customer_send_allowed remains false.",
    "No ticket/order/product mutation from assisted mode.",
    "Session-only graph output; no persistence of draft bodies to review JSONL.",
    "Continue manual sandbox/assisted review logging during pilot.",
)

_BASE_PILOT_GUARDRAILS: tuple[str, ...] = (
    "Keep OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED=true only for pilot cohort.",
    "Keep execution_allowed=false and customer_send_allowed=false in all paths.",
    "Do not auto-approve drafts or suggested actions.",
    "Do not replace existing operator console workflow; assisted mode is additive.",
    "No production graph or production API calls from pilot console sessions.",
    "Escalate pilot incidents via existing HITL channels only.",
)

_FORBIDDEN_OUTPUT_TOKENS = (
    "conversation transcript",
    "gold_reference_reply",
    '"messages"',
    "raw_prompt",
    "retrieved_context",
    '"snippet":',
    "draft_reply",
    "reviewer_notes",
)


class CriterionStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class OverallPilotReadinessStatus(StrEnum):
    NOT_READY = "not_ready_for_pilot"
    READY_WITH_GUARDRAILS = "ready_with_guardrails"
    READY_FOR_LIMITED_INTERNAL_PILOT = "ready_for_limited_internal_pilot"


@dataclass(frozen=True)
class AssistedPilotCriterionResult:
    """One pilot readiness criterion evaluation."""

    criterion_name: str
    target: str
    observed: str | None
    status: str
    notes: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "criterion_name": self.criterion_name,
            "target": self.target,
            "observed": self.observed,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class AssistedPilotRecommendation:
    """Recommended pilot action or guardrail."""

    category: str
    recommendation: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class AssistedPilotInputReports:
    """Loaded aggregate summaries for pilot readiness."""

    graduation: dict[str, Any] | None
    readiness: dict[str, Any] | None
    knowledge_coverage: dict[str, Any] | None
    assisted_metrics: dict[str, Any] | None
    draft_metrics: dict[str, Any] | None
    consistency: dict[str, Any] | None
    draft_quality_slice: dict[str, Any] | None
    action_mismatch: dict[str, Any] | None


@dataclass(frozen=True)
class AssistedPilotReadinessSummary:
    """Full assisted-mode pilot readiness report."""

    evaluation_timestamp_utc: str
    overall_status: str
    criteria_results: tuple[AssistedPilotCriterionResult, ...]
    blocking_issues: tuple[str, ...]
    advisory_issues: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    pilot_scope: tuple[str, ...]
    required_guardrails: tuple[str, ...]
    recommendations: tuple[AssistedPilotRecommendation, ...]
    recommended_next_step: str
    source_reports: dict[str, str | None]
    missing_report_warnings: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "evaluation_timestamp_utc": self.evaluation_timestamp_utc,
            "overall_status": self.overall_status,
            "criteria_results": [item.to_json_dict() for item in self.criteria_results],
            "blocking_issues": list(self.blocking_issues),
            "advisory_issues": list(self.advisory_issues),
            "remaining_risks": list(self.remaining_risks),
            "pilot_scope": list(self.pilot_scope),
            "required_guardrails": list(self.required_guardrails),
            "recommendations": [item.to_json_dict() for item in self.recommendations],
            "recommended_next_step": self.recommended_next_step,
            "source_reports": dict(self.source_reports),
            "missing_report_warnings": list(self.missing_report_warnings),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _format_rate(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.1%}"


def _result(
    name: str,
    *,
    target: str,
    observed: str | None,
    status: str,
    notes: str | None = None,
) -> AssistedPilotCriterionResult:
    return AssistedPilotCriterionResult(
        criterion_name=name,
        target=target,
        observed=observed,
        status=status,
        notes=notes,
    )


def _evaluate_count_zero(
    name: str,
    *,
    observed_count: int | None,
    label: str,
    missing_note: str,
) -> AssistedPilotCriterionResult:
    target = f"{label} == 0"
    if observed_count is None:
        return _result(
            name,
            target=target,
            observed=None,
            status=CriterionStatus.WARNING.value,
            notes=missing_note,
        )
    observed = str(observed_count)
    if observed_count == 0:
        return _result(name, target=target, observed=observed, status=CriterionStatus.PASS.value)
    return _result(
        name,
        target=target,
        observed=observed,
        status=CriterionStatus.FAIL.value,
        notes=f"{label} must remain zero for pilot",
    )


def _evaluate_rate_min(
    name: str,
    *,
    observed_rate: float | None,
    minimum: float,
    target_label: str,
    missing_note: str,
    critical: bool = False,
) -> AssistedPilotCriterionResult:
    target = f"{target_label} >= {minimum:.0%}"
    if observed_rate is None:
        status = CriterionStatus.FAIL.value if critical else CriterionStatus.WARNING.value
        return _result(name, target=target, observed=None, status=status, notes=missing_note)
    observed = _format_rate(observed_rate)
    if observed_rate >= minimum:
        return _result(name, target=target, observed=observed, status=CriterionStatus.PASS.value)
    status = CriterionStatus.FAIL.value if critical else CriterionStatus.WARNING.value
    return _result(
        name,
        target=target,
        observed=observed,
        status=status,
        notes=f"below minimum {minimum:.0%}",
    )


def _evaluate_rate_max(
    name: str,
    *,
    observed_rate: float | None,
    warn_max: float,
    fail_max: float,
    target_label: str,
    missing_note: str,
) -> AssistedPilotCriterionResult:
    target = f"{target_label} <= {warn_max:.0%} (warn), <= {fail_max:.0%} (fail)"
    if observed_rate is None:
        return _result(
            name,
            target=target,
            observed=None,
            status=CriterionStatus.WARNING.value,
            notes=missing_note,
        )
    observed = _format_rate(observed_rate)
    if observed_rate <= warn_max:
        return _result(name, target=target, observed=observed, status=CriterionStatus.PASS.value)
    if observed_rate <= fail_max:
        return _result(
            name,
            target=target,
            observed=observed,
            status=CriterionStatus.WARNING.value,
            notes=f"above advisory threshold {warn_max:.0%}",
        )
    return _result(
        name,
        target=target,
        observed=observed,
        status=CriterionStatus.FAIL.value,
        notes=f"above fail threshold {fail_max:.0%}",
    )


def load_pilot_input_reports(
    *,
    graduation_path: Path | str = DEFAULT_GRADUATION_SUMMARY_PATH,
    readiness_path: Path | str = DEFAULT_READINESS_SUMMARY_PATH,
    knowledge_path: Path | str = DEFAULT_COVERAGE_SUMMARY_PATH,
    assisted_metrics_path: Path | str = DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
    draft_metrics_path: Path | str = DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
    consistency_path: Path | str = DEFAULT_CONSISTENCY_SUMMARY_PATH,
    draft_quality_slice_path: Path | str = DEFAULT_DRAFT_QUALITY_SLICE_SUMMARY_PATH,
    action_mismatch_path: Path | str = DEFAULT_ACTION_MISMATCH_SUMMARY_PATH,
) -> AssistedPilotInputReports:
    return AssistedPilotInputReports(
        graduation=load_summary_json(graduation_path),
        readiness=load_summary_json(readiness_path),
        knowledge_coverage=load_summary_json(knowledge_path),
        assisted_metrics=load_summary_json(assisted_metrics_path),
        draft_metrics=load_summary_json(draft_metrics_path),
        consistency=load_summary_json(consistency_path),
        draft_quality_slice=load_summary_json(draft_quality_slice_path),
        action_mismatch=load_summary_json(action_mismatch_path),
    )


def _missing_report_warnings(reports: AssistedPilotInputReports) -> tuple[str, ...]:
    warnings: list[str] = []
    required = (
        ("graduation_summary", reports.graduation),
        ("readiness_summary", reports.readiness),
        ("knowledge_coverage_summary", reports.knowledge_coverage),
        ("assisted_review_metrics_summary", reports.assisted_metrics),
    )
    optional = (
        ("draft_review_metrics_summary", reports.draft_metrics),
        ("console_graph_consistency_summary", reports.consistency),
        ("draft_quality_slice_analysis_summary", reports.draft_quality_slice),
        ("action_mismatch_analysis_summary", reports.action_mismatch),
    )
    for label, payload in required:
        if payload is None:
            warnings.append(f"required report missing: {label}")
    for label, payload in optional:
        if payload is None:
            warnings.append(f"optional report missing: {label}")
    return tuple(warnings)


def _min_node_success_rate(readiness: dict[str, Any] | None) -> float | None:
    if not readiness:
        return None
    rates = readiness.get("node_success_rates")
    if not isinstance(rates, dict) or not rates:
        return None
    values = [float(value) for value in rates.values() if value is not None]
    return min(values) if values else None


def _graph_error_rate(readiness: dict[str, Any] | None) -> float | None:
    if not readiness:
        return None
    total = readiness.get("total_runs")
    failed = readiness.get("failed_runs")
    if total is None or failed is None:
        return None
    total_int = int(total)
    if total_int <= 0:
        return None
    return int(failed) / total_int


def _consistency_mismatch_rate(consistency: dict[str, Any] | None) -> float | None:
    if consistency is None:
        return None
    room_count = int(consistency.get("room_count") or 0)
    status_counts = consistency.get("status_counts") or {}
    if room_count <= 0 or not isinstance(status_counts, dict):
        return None
    mismatch_count = int(status_counts.get("mismatch") or 0)
    return mismatch_count / room_count


def evaluate_assisted_pilot_readiness(
    reports: AssistedPilotInputReports,
) -> tuple[
    tuple[AssistedPilotCriterionResult, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    str,
    str,
    tuple[AssistedPilotRecommendation, ...],
]:
    """Evaluate pilot criteria; return criteria, issues, risks, status, recommendations."""
    criteria: list[AssistedPilotCriterionResult] = []
    remaining_risks: list[str] = []

    graduation_status = (
        str(reports.graduation.get("overall_status") or "") if reports.graduation else None
    )
    if reports.graduation is None:
        criteria.append(
            _result(
                "graduation_ready",
                target=_GRADUATION_READY_TARGET,
                observed=None,
                status=CriterionStatus.FAIL.value,
                notes="graduation summary missing",
            ),
        )
    elif graduation_status == OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value:
        criteria.append(
            _result(
                "graduation_ready",
                target=_GRADUATION_READY_TARGET,
                observed=graduation_status,
                status=CriterionStatus.PASS.value,
            ),
        )
    elif graduation_status == OverallGraduationStatus.CONDITIONALLY_READY.value:
        criteria.append(
            _result(
                "graduation_ready",
                target=_GRADUATION_READY_TARGET,
                observed=graduation_status,
                status=CriterionStatus.WARNING.value,
                notes="graduation is conditionally ready; pilot should stay limited",
            ),
        )
        remaining_risks.append("Sandbox graduation is only conditionally ready.")
    else:
        criteria.append(
            _result(
                "graduation_ready",
                target=_GRADUATION_READY_TARGET,
                observed=graduation_status or "missing",
                status=CriterionStatus.FAIL.value,
                notes="graduation gate not satisfied for assisted pilot",
            ),
        )

    criteria.append(
        _result(
            "assisted_mode_capability",
            target="operator-assisted mode available behind feature flag",
            observed="OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED",
            status=(
                CriterionStatus.PASS.value
                if graduation_status
                == OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value
                else CriterionStatus.WARNING.value
            ),
            notes=(
                "Enable flag only for pilot operators after readiness sign-off"
                if graduation_status
                == OverallGraduationStatus.READY_FOR_OPERATOR_ASSISTED_PHASE.value
                else "await graduation before enabling assisted mode flag"
            ),
        ),
    )

    readiness = reports.readiness
    exec_count = (
        int(readiness["execution_allowed_true_count"])
        if readiness and readiness.get("execution_allowed_true_count") is not None
        else None
    )
    send_count = (
        int(readiness["customer_send_allowed_true_count"])
        if readiness and readiness.get("customer_send_allowed_true_count") is not None
        else None
    )
    safety_rate = (
        float(readiness["safety_passed_rate"])
        if readiness and readiness.get("safety_passed_rate") is not None
        else None
    )
    human_review_ready = (
        float(readiness["human_review_ready_rate"])
        if readiness and readiness.get("human_review_ready_rate") is not None
        else None
    )

    criteria.extend(
        [
            _evaluate_count_zero(
                "execution_disabled",
                observed_count=exec_count,
                label="execution_allowed_true_count",
                missing_note="readiness summary unavailable",
            ),
            _evaluate_count_zero(
                "customer_send_disabled",
                observed_count=send_count,
                label="customer_send_allowed_true_count",
                missing_note="readiness summary unavailable",
            ),
            _evaluate_rate_min(
                "safety_passed_rate",
                observed_rate=safety_rate,
                minimum=SAFETY_PASSED_RATE_MIN,
                target_label="safety_passed_rate",
                missing_note="readiness summary unavailable",
                critical=True,
            ),
            _evaluate_rate_min(
                "human_review_ready_rate",
                observed_rate=human_review_ready,
                minimum=HUMAN_REVIEW_READY_RATE_MIN,
                target_label="human_review_ready_rate",
                missing_note="readiness summary unavailable",
            ),
        ],
    )

    criteria.append(
        _result(
            "human_review_no_auto_send",
            target="no auto-send; human_review_required enforced in graph",
            observed=_format_rate(human_review_ready),
            status=(
                CriterionStatus.PASS.value
                if human_review_ready is not None
                and human_review_ready >= HUMAN_REVIEW_READY_RATE_MIN
                else CriterionStatus.WARNING.value
            ),
            notes="pilot must not bypass HITL send controls",
        ),
    )

    min_node = _min_node_success_rate(readiness)
    criteria.append(
        _evaluate_rate_min(
            "graph_node_success",
            observed_rate=min_node,
            minimum=NODE_SUCCESS_MIN,
            target_label="min node_success_rate",
            missing_note="readiness summary unavailable",
            critical=True,
        ),
    )

    error_rate = _graph_error_rate(readiness)
    criteria.append(
        _evaluate_rate_max(
            "graph_error_rate",
            observed_rate=error_rate,
            warn_max=GRAPH_ERROR_RATE_MAX,
            fail_max=GRAPH_ERROR_RATE_MAX,
            target_label="batch graph_error_rate",
            missing_note="readiness summary unavailable",
        ),
    )
    if error_rate is not None and error_rate > GRAPH_ERROR_RATE_MAX:
        remaining_risks.append("Sandbox batch error rate exceeds pilot comfort threshold.")

    knowledge = reports.knowledge_coverage
    coverage_rate = (
        float(knowledge["coverage_rate"])
        if knowledge and knowledge.get("coverage_rate") is not None
        else None
    )
    criteria.append(
        _evaluate_rate_min(
            "policy_knowledge_coverage",
            observed_rate=coverage_rate,
            minimum=POLICY_COVERAGE_MIN,
            target_label="policy_relevant coverage_rate",
            missing_note="knowledge coverage summary unavailable",
        ),
    )

    assisted = reports.assisted_metrics
    assisted_useful = (
        float(assisted["assisted_mode_usefulness_rate"])
        if assisted and assisted.get("assisted_mode_usefulness_rate") is not None
        else None
    )
    assisted_quality = (
        float(assisted["overall_assisted_quality_rate"])
        if assisted and assisted.get("overall_assisted_quality_rate") is not None
        else None
    )
    assisted_reviews = int(assisted["total_reviews"]) if assisted else None

    criteria.extend(
        [
            _evaluate_rate_min(
                "assisted_mode_usefulness",
                observed_rate=assisted_useful,
                minimum=ASSISTED_USEFULNESS_MIN,
                target_label="assisted_mode_usefulness_rate",
                missing_note="assisted review metrics summary unavailable",
            ),
            _evaluate_rate_min(
                "overall_assisted_quality",
                observed_rate=assisted_quality,
                minimum=ASSISTED_QUALITY_MIN,
                target_label="overall_assisted_quality_rate",
                missing_note="assisted review metrics summary unavailable",
            ),
        ],
    )

    if assisted_reviews is not None and assisted_reviews < MIN_ASSISTED_REVIEWS_ADVISORY:
        criteria.append(
            _result(
                "assisted_review_sample_size",
                target=f"total_reviews >= {MIN_ASSISTED_REVIEWS_ADVISORY} (advisory)",
                observed=str(assisted_reviews),
                status=CriterionStatus.WARNING.value,
                notes="low assisted review sample; interpret usefulness cautiously",
            ),
        )
        remaining_risks.append(
            f"Only {assisted_reviews} assisted-mode review(s) logged; "
            "expand pilot feedback sample.",
        )
    elif assisted and assisted.get("top_review_issues"):
        issues = assisted["top_review_issues"]
        if isinstance(issues, dict):
            for issue, count in sorted(
                issues.items(),
                key=lambda item: (-int(item[1]), item[0]),
            )[:3]:
                if int(count) > 0:
                    remaining_risks.append(
                        f"Assisted review issue `{issue}` flagged {count} time(s).",
                    )

    draft = reports.draft_metrics
    usable_rate = (
        float(draft["usable_rate"]) if draft and draft.get("usable_rate") is not None else None
    )
    hallucination_rate = (
        float(draft["hallucination_rate"])
        if draft and draft.get("hallucination_rate") is not None
        else None
    )
    verbosity_rate = (
        float(draft["verbosity_rate"])
        if draft and draft.get("verbosity_rate") is not None
        else None
    )

    criteria.append(
        _evaluate_rate_min(
            "draft_usable_rate",
            observed_rate=usable_rate,
            minimum=DRAFT_USABLE_RATE_MIN,
            target_label="usable_rate",
            missing_note="draft review metrics unavailable (advisory)",
        ),
    )

    if hallucination_rate is None:
        criteria.append(
            _result(
                "draft_hallucination_rate",
                target="hallucination_rate == 0 (preferred)",
                observed=None,
                status=CriterionStatus.WARNING.value,
                notes="draft review metrics unavailable",
            ),
        )
    elif hallucination_rate == 0.0:
        criteria.append(
            _result(
                "draft_hallucination_rate",
                target="hallucination_rate == 0 (preferred)",
                observed=_format_rate(hallucination_rate),
                status=CriterionStatus.PASS.value,
            ),
        )
    else:
        criteria.append(
            _result(
                "draft_hallucination_rate",
                target="hallucination_rate == 0 (preferred)",
                observed=_format_rate(hallucination_rate),
                status=CriterionStatus.WARNING.value,
                notes="non-zero hallucination flags in draft reviews",
            ),
        )
        remaining_risks.append("Operators flagged hallucination/unsupported claims in drafts.")

    if verbosity_rate is None:
        criteria.append(
            _result(
                "draft_verbosity",
                target=f"verbosity_rate <= {VERBOSITY_RATE_WARN:.0%} (acceptable)",
                observed=None,
                status=CriterionStatus.WARNING.value,
                notes="draft review metrics unavailable",
            ),
        )
    elif verbosity_rate <= VERBOSITY_RATE_WARN:
        criteria.append(
            _result(
                "draft_verbosity",
                target=f"verbosity_rate <= {VERBOSITY_RATE_WARN:.0%} (acceptable)",
                observed=_format_rate(verbosity_rate),
                status=CriterionStatus.PASS.value,
            ),
        )
    else:
        criteria.append(
            _result(
                "draft_verbosity",
                target=f"verbosity_rate <= {VERBOSITY_RATE_WARN:.0%} (acceptable)",
                observed=_format_rate(verbosity_rate),
                status=CriterionStatus.WARNING.value,
                notes="verbosity above advisory comfort threshold",
            ),
        )

    criteria.append(
        _evaluate_rate_max(
            "console_graph_consistency",
            observed_rate=_consistency_mismatch_rate(reports.consistency),
            warn_max=CONSISTENCY_MISMATCH_WARN,
            fail_max=CONSISTENCY_MISMATCH_FAIL,
            target_label="console_graph_mismatch_rate",
            missing_note="console graph consistency summary unavailable",
        ),
    )

    if reports.action_mismatch is not None:
        total_mismatches = int(reports.action_mismatch.get("total_action_mismatches") or 0)
        criteria.append(
            _result(
                "action_mismatch_analysis",
                target="action mismatches monitored (advisory)",
                observed=str(total_mismatches),
                status=(
                    CriterionStatus.WARNING.value
                    if total_mismatches > 0
                    else CriterionStatus.PASS.value
                ),
                notes="review suggested_action calibration during pilot",
            ),
        )
        if total_mismatches > 0:
            remaining_risks.append(
                f"{total_mismatches} offline draft review action mismatch(es) on record.",
            )

    if reports.draft_quality_slice is not None:
        weak_slices = reports.draft_quality_slice.get("weak_slices") or []
        weak_count = len(weak_slices) if isinstance(weak_slices, list) else 0
        criteria.append(
            _result(
                "draft_quality_slices",
                target="no dominant weak slices (advisory)",
                observed=str(weak_count),
                status=(
                    CriterionStatus.WARNING.value if weak_count > 0 else CriterionStatus.PASS.value
                ),
                notes="see draft quality slice report for weak intent/action buckets",
            ),
        )
        if weak_count > 0:
            remaining_risks.append(
                f"{weak_count} weak draft-quality slice(s) identified in offline reviews.",
            )

    unique_risks = tuple(dict.fromkeys(remaining_risks))
    blocking, advisory, overall, next_step, recommendations = _finalize_pilot_evaluation(
        tuple(criteria),
        remaining_risks=unique_risks,
        graduation_status=graduation_status,
    )
    return tuple(criteria), blocking, advisory, unique_risks, overall, next_step, recommendations


def _finalize_pilot_evaluation(
    criteria: tuple[AssistedPilotCriterionResult, ...],
    *,
    remaining_risks: tuple[str, ...],
    graduation_status: str | None,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    str,
    str,
    tuple[AssistedPilotRecommendation, ...],
]:
    blocking: list[str] = []
    advisory: list[str] = []

    critical_failures = [
        item
        for item in criteria
        if item.status == CriterionStatus.FAIL.value and item.criterion_name in _CRITICAL_CRITERIA
    ]
    other_failures = [
        item
        for item in criteria
        if item.status == CriterionStatus.FAIL.value
        and item.criterion_name not in _CRITICAL_CRITERIA
    ]
    warnings = [item for item in criteria if item.status == CriterionStatus.WARNING.value]

    for item in critical_failures + other_failures:
        blocking.append(f"{item.criterion_name}: {item.notes or item.target}")
    for item in warnings:
        advisory.append(f"{item.criterion_name}: {item.notes or item.target}")

    if critical_failures or other_failures:
        overall = OverallPilotReadinessStatus.NOT_READY.value
        next_step = (
            "Do not start limited internal pilot until blocking pilot readiness criteria pass."
        )
    elif warnings:
        overall = OverallPilotReadinessStatus.READY_WITH_GUARDRAILS.value
        next_step = (
            "Begin a limited internal pilot with documented guardrails and weekly HITL review."
        )
    else:
        overall = OverallPilotReadinessStatus.READY_FOR_LIMITED_INTERNAL_PILOT.value
        next_step = "Proceed with limited internal operator-assisted pilot per scoped guardrails."

    recommendations = _pilot_recommendations(
        overall_status=overall,
        graduation_status=graduation_status,
        criteria=criteria,
    )
    return tuple(blocking), tuple(advisory), overall, next_step, recommendations


def _pilot_recommendations(
    *,
    overall_status: str,
    graduation_status: str | None,
    criteria: Sequence[AssistedPilotCriterionResult],
) -> tuple[AssistedPilotRecommendation, ...]:
    items: list[AssistedPilotRecommendation] = [
        AssistedPilotRecommendation("scope", scope) for scope in _PILOT_SCOPE
    ]
    items.extend(AssistedPilotRecommendation("guardrail", text) for text in _BASE_PILOT_GUARDRAILS)
    if overall_status != OverallPilotReadinessStatus.READY_FOR_LIMITED_INTERNAL_PILOT.value:
        items.append(
            AssistedPilotRecommendation(
                "gate",
                "Complete sandbox graduation and pilot metrics before expanding operator cohort.",
            ),
        )
    if graduation_status == OverallGraduationStatus.CONDITIONALLY_READY.value:
        items.append(
            AssistedPilotRecommendation(
                "graduation",
                "Treat graduation advisory issues as pilot exit criteria.",
            ),
        )
    for item in criteria:
        if (
            item.status == CriterionStatus.WARNING.value
            and item.criterion_name == "console_graph_consistency"
        ):
            items.append(
                AssistedPilotRecommendation(
                    "consistency",
                    "Document console vs graph explainable differences in pilot runbook.",
                ),
            )
    seen: set[tuple[str, str]] = set()
    deduped: list[AssistedPilotRecommendation] = []
    for rec in items:
        key = (rec.category, rec.recommendation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)
    return tuple(deduped)


def _pilot_guardrails(
    *,
    overall_status: str,
    criteria: Sequence[AssistedPilotCriterionResult],
) -> tuple[str, ...]:
    extras: list[str] = []
    if overall_status == OverallPilotReadinessStatus.READY_WITH_GUARDRAILS.value:
        extras.append("Weekly pilot review of assisted_mode_usefulness and safety flags.")
    for item in criteria:
        if (
            item.criterion_name == "policy_knowledge_coverage"
            and item.status != CriterionStatus.PASS.value
        ):
            extras.append(
                "Track policy-relevant tickets with zero knowledge hints during pilot.",
            )
    return tuple(dict.fromkeys([*_BASE_PILOT_GUARDRAILS, *extras]))


def build_assisted_pilot_readiness_summary(
    reports: AssistedPilotInputReports,
    *,
    evaluation_timestamp_utc: str | None = None,
    source_reports: Mapping[str, str | None] | None = None,
) -> AssistedPilotReadinessSummary:
    """Build full pilot readiness summary."""
    (
        criteria,
        blocking,
        advisory,
        remaining_risks,
        overall,
        next_step,
        recommendations,
    ) = evaluate_assisted_pilot_readiness(reports)
    return AssistedPilotReadinessSummary(
        evaluation_timestamp_utc=evaluation_timestamp_utc or _utc_now_iso(),
        overall_status=overall,
        criteria_results=criteria,
        blocking_issues=blocking,
        advisory_issues=advisory,
        remaining_risks=remaining_risks,
        pilot_scope=_PILOT_SCOPE,
        required_guardrails=_pilot_guardrails(overall_status=overall, criteria=criteria),
        recommendations=recommendations,
        recommended_next_step=next_step,
        source_reports=dict(source_reports or {}),
        missing_report_warnings=_missing_report_warnings(reports),
    )


def render_assisted_pilot_readiness_markdown(summary: AssistedPilotReadinessSummary) -> str:
    """Render pilot readiness markdown (safe fields only)."""
    lines = [
        "# Operator-assisted mode pilot readiness",
        "",
        f"- **evaluation_timestamp_utc:** {summary.evaluation_timestamp_utc}",
        f"- **overall_status:** {summary.overall_status}",
        "",
        "## Overall decision",
        "",
        summary.recommended_next_step,
        "",
        "## Criteria",
        "",
        "| Criterion | Target | Observed | Status | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in summary.criteria_results:
        lines.append(
            f"| {item.criterion_name} | {item.target} | {item.observed or '—'} | "
            f"{item.status} | {item.notes or '—'} |",
        )

    lines.extend(["", "## Recommended pilot scope", ""])
    for scope in summary.pilot_scope:
        lines.append(f"- {scope}")

    lines.extend(["", "## Required guardrails", ""])
    for guardrail in summary.required_guardrails:
        lines.append(f"- {guardrail}")

    lines.extend(["", "## Remaining risks", ""])
    if summary.remaining_risks:
        for risk in summary.remaining_risks:
            lines.append(f"- {risk}")
    else:
        lines.append("- None identified from current aggregate reports.")

    lines.extend(["", "## Blocking issues", ""])
    if summary.blocking_issues:
        for issue in summary.blocking_issues:
            lines.append(f"- {issue}")
    else:
        lines.append("- None")

    lines.extend(["", "## Advisory issues", ""])
    if summary.advisory_issues:
        for issue in summary.advisory_issues:
            lines.append(f"- {issue}")
    else:
        lines.append("- None")

    if summary.missing_report_warnings:
        lines.extend(["", "## Missing report warnings", ""])
        for warning in summary.missing_report_warnings:
            lines.append(f"- {warning}")

    lines.extend(["", "## Recommendations", ""])
    for rec in summary.recommendations:
        lines.append(f"- **{rec.category}:** {rec.recommendation}")

    lines.extend(["", "## Next recommended step", "", summary.recommended_next_step, ""])

    if summary.source_reports:
        lines.extend(["", "## Source reports", ""])
        for key, path in sorted(summary.source_reports.items()):
            lines.append(f"- **{key}:** {path or '—'}")

    lines.extend(
        [
            "",
            "## Governance",
            "",
            (
                "- Pilot readiness assessment only — does not enable send, "
                "execution, or auto-approval."
            ),
            (
                "- Limited internal pilot; assisted mode remains additive "
                "to existing console workflow."
            ),
            (
                "- No prompts, transcripts, retrieval snippets, draft bodies, "
                "or secrets in this report."
            ),
            "",
        ],
    )
    return "\n".join(lines)


def assert_assisted_pilot_readiness_output_safe(content: str) -> None:
    """Fail closed if pilot readiness output contains forbidden content."""
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                f"assisted pilot readiness output must not contain forbidden token: {token}",
            )
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise ValueError(
                f"assisted pilot readiness output must not contain forbidden token: {token}",
            )
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError("assisted pilot readiness output must not contain API key patterns")


def build_assisted_mode_pilot_readiness_report(
    *,
    graduation_path: Path | str = DEFAULT_GRADUATION_SUMMARY_PATH,
    readiness_path: Path | str = DEFAULT_READINESS_SUMMARY_PATH,
    knowledge_path: Path | str = DEFAULT_COVERAGE_SUMMARY_PATH,
    assisted_metrics_path: Path | str = DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
    draft_metrics_path: Path | str = DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
    consistency_path: Path | str = DEFAULT_CONSISTENCY_SUMMARY_PATH,
    draft_quality_slice_path: Path | str = DEFAULT_DRAFT_QUALITY_SLICE_SUMMARY_PATH,
    action_mismatch_path: Path | str = DEFAULT_ACTION_MISMATCH_SUMMARY_PATH,
    summary_output: Path = DEFAULT_PILOT_READINESS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_PILOT_READINESS_REPORT_PATH,
    evaluation_timestamp_utc: str | None = None,
) -> AssistedPilotReadinessSummary:
    """Load inputs, evaluate pilot readiness, and write JSON + markdown reports."""
    reports = load_pilot_input_reports(
        graduation_path=graduation_path,
        readiness_path=readiness_path,
        knowledge_path=knowledge_path,
        assisted_metrics_path=assisted_metrics_path,
        draft_metrics_path=draft_metrics_path,
        consistency_path=consistency_path,
        draft_quality_slice_path=draft_quality_slice_path,
        action_mismatch_path=action_mismatch_path,
    )
    source_reports = {
        "graduation_summary": str(graduation_path),
        "readiness_summary": str(readiness_path),
        "knowledge_coverage_summary": str(knowledge_path),
        "assisted_review_metrics_summary": str(assisted_metrics_path),
        "draft_review_metrics_summary": str(draft_metrics_path),
        "console_graph_consistency_summary": str(consistency_path),
        "draft_quality_slice_analysis_summary": str(draft_quality_slice_path),
        "action_mismatch_analysis_summary": str(action_mismatch_path),
    }
    summary = build_assisted_pilot_readiness_summary(
        reports,
        evaluation_timestamp_utc=evaluation_timestamp_utc,
        source_reports=source_reports,
    )
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_assisted_pilot_readiness_markdown(summary)
    assert_assisted_pilot_readiness_output_safe(json_text)
    assert_assisted_pilot_readiness_output_safe(markdown)
    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary
