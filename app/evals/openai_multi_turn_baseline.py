"""OpenAI multi-turn behavioral baseline — freeze, compare, and drift classification."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.multi_turn_eval_runner import (
    DEFAULT_SCENARIOS_PATH,
    EvalScenario,
    EvalScenarioResult,
    EvalSuiteSummary,
    assert_report_safe,
    run_multi_turn_eval_suite,
)
from app.evals.multi_turn_failure_triage import run_failure_triage
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

DEFAULT_OPENAI_BASELINE_DIR = Path("data/evals/golden_outputs/openai_baseline")
DEFAULT_FREEZE_SUMMARY_JSON = Path("reports/openai_baseline_freeze_summary.json")
DEFAULT_FREEZE_REPORT_MD = Path("reports/openai_baseline_freeze_report.md")
DEFAULT_COMPARE_SUMMARY_JSON = Path("reports/openai_baseline_compare_summary.json")
DEFAULT_COMPARE_REPORT_MD = Path("reports/openai_baseline_compare_report.md")
MANIFEST_FILENAME = "manifest.json"

_FORBIDDEN_BASELINE_KEYS = frozenset(
    {
        "raw_prompt",
        "chain_of_thought",
        "hidden_reasoning",
        "reviewer_thoughts",
        "knowledge_hints_for_prompt",
        "draft_reply",
        "messages",
        "transcript",
        "conversation_transcript",
        "embeddings",
    },
)

_CRITICAL_SCENARIO_IDS = frozenset(
    {
        "closed_ticket_skip",
        "repeated_tracking_ask_prevention",
        "cancellation_no_reason_ask",
    },
)

_REPEATED_ASK_CATEGORIES = frozenset(
    {
        "repeated_ask_prevention",
        "tracking_fulfillment",
    },
)

_POLICY_CATEGORIES = frozenset(
    {
        "settlement_policy",
        "settlement_bank_policy",
    },
)

_MULTI_SPACE_RE = re.compile(r"\s+")
_REPEATED_DOTS_RE = re.compile(r"\.{2,}")
_ELLIPSIS_RE = re.compile(r"…+")


class BaselineDriftClass(StrEnum):
    """Drift severity for baseline comparison."""

    NONE = "none"
    ACCEPTABLE = "acceptable"
    REVIEW_REQUIRED = "review_required"
    CRITICAL_REGRESSION = "critical_regression"


@dataclass(frozen=True)
class BaselineScenarioRecord:
    """Frozen behavioral fingerprint for one scenario (no draft body)."""

    scenario_id: str
    draft_fingerprint: str | None
    detected_intent: str | None
    suggested_action: str | None
    reflection_rewrite_applied: bool | None
    should_generate_draft: bool | None
    policy_question_type: str | None
    reflection_issue_types: tuple[str, ...] = ()
    graph_status: str | None = None
    eval_passed: bool = False
    skip_reason: str | None = None
    updated_at_utc: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "draft_fingerprint": self.draft_fingerprint,
            "detected_intent": self.detected_intent,
            "suggested_action": self.suggested_action,
            "reflection_rewrite_applied": self.reflection_rewrite_applied,
            "should_generate_draft": self.should_generate_draft,
            "policy_question_type": self.policy_question_type,
            "reflection_issue_types": list(self.reflection_issue_types),
            "graph_status": self.graph_status,
            "eval_passed": self.eval_passed,
            "skip_reason": self.skip_reason,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> BaselineScenarioRecord:
        issues_raw = payload.get("reflection_issue_types") or []
        issues = tuple(str(item) for item in issues_raw if str(item).strip())
        rewrite_raw = payload.get("reflection_rewrite_applied")
        reflection_rewrite_applied = bool(rewrite_raw) if rewrite_raw is not None else None
        should_raw = payload.get("should_generate_draft")
        should_generate_draft = bool(should_raw) if should_raw is not None else None
        fp = payload.get("draft_fingerprint")
        return cls(
            scenario_id=str(payload.get("scenario_id") or "").strip(),
            draft_fingerprint=str(fp).strip() if fp else None,
            detected_intent=_optional_str(payload.get("detected_intent")),
            suggested_action=_optional_str(payload.get("suggested_action")),
            reflection_rewrite_applied=reflection_rewrite_applied,
            should_generate_draft=should_generate_draft,
            policy_question_type=_optional_str(payload.get("policy_question_type")),
            reflection_issue_types=issues,
            graph_status=_optional_str(payload.get("graph_status")),
            eval_passed=bool(payload.get("eval_passed")),
            skip_reason=_optional_str(payload.get("skip_reason")),
            updated_at_utc=str(payload.get("updated_at_utc") or ""),
        )


@dataclass(frozen=True)
class BaselineReflectionMetrics:
    """Aggregate reflection stats frozen with the baseline."""

    rewrite_applied_count: int
    rewrite_rate: float
    saved_bad_draft_count: int
    save_rate: float
    reflection_reviewed_count: int
    issue_type_counts: dict[str, int] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "rewrite_applied_count": self.rewrite_applied_count,
            "rewrite_rate": self.rewrite_rate,
            "saved_bad_draft_count": self.saved_bad_draft_count,
            "save_rate": self.save_rate,
            "reflection_reviewed_count": self.reflection_reviewed_count,
            "issue_type_counts": dict(self.issue_type_counts),
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> BaselineReflectionMetrics:
        counts_raw = payload.get("issue_type_counts") or {}
        counts = (
            {str(k): int(v) for k, v in counts_raw.items()} if isinstance(counts_raw, dict) else {}
        )
        return cls(
            rewrite_applied_count=int(payload.get("rewrite_applied_count") or 0),
            rewrite_rate=float(payload.get("rewrite_rate") or 0.0),
            saved_bad_draft_count=int(payload.get("saved_bad_draft_count") or 0),
            save_rate=float(payload.get("save_rate") or 0.0),
            reflection_reviewed_count=int(payload.get("reflection_reviewed_count") or 0),
            issue_type_counts=counts,
        )


@dataclass(frozen=True)
class BaselineManifest:
    """Safe metadata for a frozen OpenAI baseline (no prompts or transcripts)."""

    baseline_id: str
    provider: str
    model: str | None
    knowledge_hints_enabled: bool
    multi_turn_context_enabled: bool
    final_draft_reflection_enabled: bool
    reflection_provider: str | None
    frozen_at_utc: str
    scenario_count: int
    eval_passed_count: int
    eval_failed_count: int
    reflection_metrics: BaselineReflectionMetrics

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "provider": self.provider,
            "model": self.model,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "multi_turn_context_enabled": self.multi_turn_context_enabled,
            "final_draft_reflection_enabled": self.final_draft_reflection_enabled,
            "reflection_provider": self.reflection_provider,
            "frozen_at_utc": self.frozen_at_utc,
            "scenario_count": self.scenario_count,
            "eval_passed_count": self.eval_passed_count,
            "eval_failed_count": self.eval_failed_count,
            "reflection_metrics": self.reflection_metrics.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> BaselineManifest:
        metrics_raw = payload.get("reflection_metrics") or {}
        metrics = (
            BaselineReflectionMetrics.from_json_dict(metrics_raw)
            if isinstance(metrics_raw, dict)
            else BaselineReflectionMetrics(
                rewrite_applied_count=0,
                rewrite_rate=0.0,
                saved_bad_draft_count=0,
                save_rate=0.0,
                reflection_reviewed_count=0,
            )
        )
        return cls(
            baseline_id=str(payload.get("baseline_id") or "openai_multi_turn"),
            provider=str(payload.get("provider") or "openai"),
            model=_optional_str(payload.get("model")),
            knowledge_hints_enabled=bool(payload.get("knowledge_hints_enabled")),
            multi_turn_context_enabled=bool(payload.get("multi_turn_context_enabled")),
            final_draft_reflection_enabled=bool(
                payload.get("final_draft_reflection_enabled"),
            ),
            reflection_provider=_optional_str(payload.get("reflection_provider")),
            frozen_at_utc=str(payload.get("frozen_at_utc") or ""),
            scenario_count=int(payload.get("scenario_count") or 0),
            eval_passed_count=int(payload.get("eval_passed_count") or 0),
            eval_failed_count=int(payload.get("eval_failed_count") or 0),
            reflection_metrics=metrics,
        )


@dataclass(frozen=True)
class BaselineDriftItem:
    """Drift detected for one scenario vs frozen baseline."""

    scenario_id: str
    drift_class: BaselineDriftClass
    reasons: tuple[str, ...]
    baseline: BaselineScenarioRecord | None
    current: BaselineScenarioRecord | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "drift_class": self.drift_class.value,
            "reasons": list(self.reasons),
            "baseline": self.baseline.to_json_dict() if self.baseline else None,
            "current": self.current.to_json_dict() if self.current else None,
        }


@dataclass(frozen=True)
class BaselineCompareSummary:
    """Aggregate baseline comparison outcome."""

    status: str
    baseline_dir: str
    manifest: BaselineManifest | None
    total_scenarios: int
    unchanged_count: int
    acceptable_drift_count: int
    review_required_count: int
    critical_regression_count: int
    missing_baseline_count: int
    missing_current_count: int
    reflection_metrics_delta: dict[str, Any]
    items: tuple[BaselineDriftItem, ...] = ()
    generated_at_utc: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": self.generated_at_utc,
            "baseline_dir": self.baseline_dir,
            "manifest": self.manifest.to_json_dict() if self.manifest else None,
            "total_scenarios": self.total_scenarios,
            "unchanged_count": self.unchanged_count,
            "acceptable_drift_count": self.acceptable_drift_count,
            "review_required_count": self.review_required_count,
            "critical_regression_count": self.critical_regression_count,
            "missing_baseline_count": self.missing_baseline_count,
            "missing_current_count": self.missing_current_count,
            "reflection_metrics_delta": self.reflection_metrics_delta,
            "items": [item.to_json_dict() for item in self.items],
        }


@dataclass(frozen=True)
class BaselineFreezeSummary:
    """Outcome of a baseline freeze run."""

    status: str
    baseline_dir: str
    update_baseline: bool
    eval_summary: EvalSuiteSummary
    manifest: BaselineManifest
    triage_real_failures: int
    triage_critical_count: int
    triage_high_count: int
    scenario_files_written: int
    generated_at_utc: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": self.generated_at_utc,
            "baseline_dir": self.baseline_dir,
            "update_baseline": self.update_baseline,
            "eval_summary": self.eval_summary.to_json_dict(),
            "manifest": self.manifest.to_json_dict(),
            "triage_real_failures": self.triage_real_failures,
            "triage_critical_count": self.triage_critical_count,
            "triage_high_count": self.triage_high_count,
            "scenario_files_written": self.scenario_files_written,
        }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_baseline_draft_text(text: str | None) -> str:
    """Normalize draft text before baseline fingerprinting (cosmetic-stable)."""
    if not text:
        return ""
    cleaned = normalize_persian_arabic_digits(text.strip())
    cleaned = cleaned.replace("\u200c", " ")
    cleaned = _ELLIPSIS_RE.sub(".", cleaned)
    cleaned = _REPEATED_DOTS_RE.sub(".", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    # Lowercase ASCII fragments only; Persian text is unchanged by lower().
    cleaned = "".join(ch.lower() if "a" <= ch <= "z" or "A" <= ch <= "Z" else ch for ch in cleaned)
    return cleaned.strip()


def compute_baseline_draft_fingerprint(draft: str | None) -> str | None:
    """SHA-256 fingerprint using baseline normalization (distinct from eval substring checks)."""
    normalized = normalize_baseline_draft_text(draft)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def assert_baseline_payload_safe(payload: Mapping[str, Any]) -> None:
    """Fail closed if baseline JSON would store forbidden internal fields."""

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_str = str(key)
                if key_str in _FORBIDDEN_BASELINE_KEYS:
                    raise ValueError(f"baseline payload forbidden key: {key_str}")
                _walk(value, f"{path}.{key_str}")
        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                _walk(item, f"{path}[{index}]")

    _walk(payload)


def scenario_record_from_eval_result(result: EvalScenarioResult) -> BaselineScenarioRecord:
    """Build a baseline record from one eval scenario result."""
    fingerprint = compute_baseline_draft_fingerprint(result.draft_reply)
    if fingerprint is None and result.draft_fingerprint:
        fingerprint = result.draft_fingerprint
    return BaselineScenarioRecord(
        scenario_id=result.scenario_id,
        draft_fingerprint=fingerprint,
        detected_intent=result.detected_intent,
        suggested_action=result.suggested_action,
        reflection_rewrite_applied=result.reflection_rewrite_applied,
        should_generate_draft=result.should_generate_draft,
        policy_question_type=result.policy_question_type,
        reflection_issue_types=result.reflection_issue_types,
        graph_status=result.graph_status,
        eval_passed=result.passed,
        skip_reason=result.skip_reason,
        updated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def reflection_metrics_from_results(
    results: Sequence[EvalScenarioResult],
) -> BaselineReflectionMetrics:
    """Aggregate reflection metrics for manifest freeze."""
    total = len(results)
    rewrite_count = sum(1 for item in results if item.reflection_rewrite_applied)
    reviewed_count = sum(1 for item in results if item.reflection_reviewed)
    save_issue_types = frozenset(
        {
            "policy_grounding_failure",
            "weak_policy_answer",
            "repeated_identifier_request",
            "unsupported_claim",
            "missing_operational_ack",
        },
    )
    saved_count = sum(
        1
        for item in results
        if item.reflection_rewrite_applied
        and any(issue in save_issue_types for issue in item.reflection_issue_types)
    )
    issue_counter: Counter[str] = Counter()
    for item in results:
        for issue in item.reflection_issue_types:
            issue_counter[issue] += 1
    rewrite_rate = (rewrite_count / total) if total else 0.0
    save_rate = (saved_count / total) if total else 0.0
    return BaselineReflectionMetrics(
        rewrite_applied_count=rewrite_count,
        rewrite_rate=rewrite_rate,
        saved_bad_draft_count=saved_count,
        save_rate=save_rate,
        reflection_reviewed_count=reviewed_count,
        issue_type_counts=dict(sorted(issue_counter.items())),
    )


def build_manifest_from_run(
    summary: EvalSuiteSummary,
    *,
    settings: AppSettings,
    reflection_metrics: BaselineReflectionMetrics,
    baseline_id: str = "openai_multi_turn_v1",
) -> BaselineManifest:
    """Build manifest metadata for a completed OpenAI eval run."""
    return BaselineManifest(
        baseline_id=baseline_id,
        provider=summary.provider,
        model=settings.openai_draft_model,
        knowledge_hints_enabled=summary.knowledge_hints_enabled,
        multi_turn_context_enabled=settings.multi_turn_context_enabled,
        final_draft_reflection_enabled=settings.final_draft_reflection_enabled,
        reflection_provider=settings.final_draft_reflection_provider,
        frozen_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        scenario_count=summary.total_scenarios,
        eval_passed_count=summary.passed_count,
        eval_failed_count=summary.failed_count,
        reflection_metrics=reflection_metrics,
    )


def load_baseline_manifest(
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
) -> BaselineManifest | None:
    path = baseline_dir / MANIFEST_FILENAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert_baseline_payload_safe(payload)
    return BaselineManifest.from_json_dict(payload)


def write_baseline_manifest(
    manifest: BaselineManifest,
    *,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
    overwrite: bool = False,
) -> Path:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_dir / MANIFEST_FILENAME
    if path.exists() and not overwrite:
        raise FileExistsError(f"baseline manifest exists: {path} (use --update-baseline)")
    payload = manifest.to_json_dict()
    assert_baseline_payload_safe(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_baseline_scenario_record(
    scenario_id: str,
    *,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
) -> BaselineScenarioRecord | None:
    path = baseline_dir / f"{scenario_id}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert_baseline_payload_safe(payload)
    return BaselineScenarioRecord.from_json_dict(payload)


def write_baseline_scenario_record(
    record: BaselineScenarioRecord,
    *,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
    overwrite: bool = False,
) -> Path:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_dir / f"{record.scenario_id}.json"
    if path.exists() and not overwrite:
        raise FileExistsError(f"baseline scenario exists: {path} (use --update-baseline)")
    payload = record.to_json_dict()
    assert_baseline_payload_safe(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_all_baseline_records(
    *,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
) -> dict[str, BaselineScenarioRecord]:
    records: dict[str, BaselineScenarioRecord] = {}
    if not baseline_dir.is_dir():
        return records
    for path in sorted(baseline_dir.glob("*.json")):
        if path.name == MANIFEST_FILENAME:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert_baseline_payload_safe(payload)
        record = BaselineScenarioRecord.from_json_dict(payload)
        if record.scenario_id:
            records[record.scenario_id] = record
    return records


def _field_equal(left: Any, right: Any) -> bool:
    return left == right


def classify_scenario_drift(
    baseline: BaselineScenarioRecord | None,
    current: BaselineScenarioRecord | None,
    *,
    scenario_category: str | None = None,
) -> BaselineDriftItem:
    """Classify drift between frozen baseline and current run."""
    scenario_id = (current or baseline).scenario_id if (current or baseline) else ""
    if baseline is None:
        return BaselineDriftItem(
            scenario_id=scenario_id,
            drift_class=BaselineDriftClass.REVIEW_REQUIRED,
            reasons=("missing_baseline_record",),
            baseline=None,
            current=current,
        )
    if current is None:
        return BaselineDriftItem(
            scenario_id=scenario_id,
            drift_class=BaselineDriftClass.REVIEW_REQUIRED,
            reasons=("missing_current_record",),
            baseline=baseline,
            current=None,
        )

    reasons: list[str] = []
    critical = False
    review = False

    if baseline.eval_passed and not current.eval_passed:
        critical = True
        reasons.append("eval_regression")

    if not _field_equal(baseline.should_generate_draft, current.should_generate_draft):
        review = True
        reasons.append("should_generate_draft_drift")
        if scenario_id in _CRITICAL_SCENARIO_IDS or scenario_category in _REPEATED_ASK_CATEGORIES:
            critical = True
            reasons.append("gating_regression")

    if not _field_equal(baseline.detected_intent, current.detected_intent):
        review = True
        reasons.append("intent_drift")

    if not _field_equal(baseline.suggested_action, current.suggested_action):
        review = True
        reasons.append("action_drift")

    if not _field_equal(baseline.reflection_rewrite_applied, current.reflection_rewrite_applied):
        review = True
        reasons.append("reflection_rewrite_drift")

    if not _field_equal(baseline.policy_question_type, current.policy_question_type):
        review = True
        reasons.append("policy_question_type_drift")

    if baseline.reflection_issue_types != current.reflection_issue_types:
        review = True
        reasons.append("reflection_issue_types_drift")

    fingerprint_drift = baseline.draft_fingerprint != current.draft_fingerprint
    if fingerprint_drift:
        if review or critical:
            if critical:
                reasons.append("draft_fingerprint_drift")
            else:
                reasons.append("draft_fingerprint_drift_with_metadata_change")
        else:
            reasons.append("draft_fingerprint_cosmetic_drift")

    if critical:
        drift_class = BaselineDriftClass.CRITICAL_REGRESSION
    elif review:
        drift_class = BaselineDriftClass.REVIEW_REQUIRED
    elif fingerprint_drift:
        drift_class = BaselineDriftClass.ACCEPTABLE
    else:
        drift_class = BaselineDriftClass.NONE

    return BaselineDriftItem(
        scenario_id=scenario_id,
        drift_class=drift_class,
        reasons=tuple(dict.fromkeys(reasons)),
        baseline=baseline,
        current=current,
    )


def compare_baseline_records(
    baseline_records: Mapping[str, BaselineScenarioRecord],
    current_records: Mapping[str, BaselineScenarioRecord],
    *,
    scenarios_by_id: Mapping[str, EvalScenario] | None = None,
    manifest: BaselineManifest | None = None,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
) -> BaselineCompareSummary:
    """Compare current records against frozen baseline."""
    all_ids = sorted(set(baseline_records) | set(current_records))
    items: list[BaselineDriftItem] = []
    counts = Counter({item.value: 0 for item in BaselineDriftClass})

    for scenario_id in all_ids:
        category = None
        if scenarios_by_id and scenario_id in scenarios_by_id:
            category = scenarios_by_id[scenario_id].category
        item = classify_scenario_drift(
            baseline_records.get(scenario_id),
            current_records.get(scenario_id),
            scenario_category=category,
        )
        items.append(item)
        counts[item.drift_class.value] += 1

    reflection_delta: dict[str, Any] = {}
    if manifest is not None and current_records:
        total = len(current_records)
        rewrite_count = sum(
            1 for record in current_records.values() if record.reflection_rewrite_applied
        )
        save_issue_types = frozenset(
            {
                "policy_grounding_failure",
                "weak_policy_answer",
                "repeated_identifier_request",
                "unsupported_claim",
                "missing_operational_ack",
            },
        )
        saved_count = sum(
            1
            for record in current_records.values()
            if record.reflection_rewrite_applied
            and any(issue in save_issue_types for issue in record.reflection_issue_types)
        )
        rewrite_rate = (rewrite_count / total) if total else 0.0
        save_rate = (saved_count / total) if total else 0.0
        reflection_delta = {
            "rewrite_applied_count_delta": (
                rewrite_count - manifest.reflection_metrics.rewrite_applied_count
            ),
            "rewrite_rate_delta": (rewrite_rate - manifest.reflection_metrics.rewrite_rate),
            "saved_bad_draft_count_delta": (
                saved_count - manifest.reflection_metrics.saved_bad_draft_count
            ),
            "save_rate_delta": (save_rate - manifest.reflection_metrics.save_rate),
        }

    critical_count = counts[BaselineDriftClass.CRITICAL_REGRESSION.value]
    status = "passed" if critical_count == 0 else "failed"
    return BaselineCompareSummary(
        status=status,
        baseline_dir=str(baseline_dir),
        manifest=manifest,
        total_scenarios=len(all_ids),
        unchanged_count=counts[BaselineDriftClass.NONE.value],
        acceptable_drift_count=counts[BaselineDriftClass.ACCEPTABLE.value],
        review_required_count=counts[BaselineDriftClass.REVIEW_REQUIRED.value],
        critical_regression_count=critical_count,
        missing_baseline_count=sum(
            1 for item in items if "missing_baseline_record" in item.reasons
        ),
        missing_current_count=sum(1 for item in items if "missing_current_record" in item.reasons),
        reflection_metrics_delta=reflection_delta,
        items=tuple(items),
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def _triage_counts(
    results: Sequence[EvalScenarioResult],
    scenarios_by_id: Mapping[str, EvalScenario],
) -> tuple[int, int, int]:
    rows = [item.to_json_dict() for item in results]
    triage = run_failure_triage(rows, scenarios_by_id=scenarios_by_id)
    critical = sum(
        1
        for item in triage.items
        if not item.acceptable_variance and item.severity.value == "critical"
    )
    high = sum(
        1 for item in triage.items if not item.acceptable_variance and item.severity.value == "high"
    )
    return triage.real_failure_count, critical, high


def freeze_openai_baseline(
    *,
    scenarios: Sequence[EvalScenario],
    settings: AppSettings | None = None,
    enable_knowledge_hints: bool = True,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
    update_baseline: bool = False,
    scenarios_path: Path = DEFAULT_SCENARIOS_PATH,
) -> BaselineFreezeSummary:
    """Run OpenAI eval suite and optionally write frozen baseline fingerprints."""
    if not update_baseline:
        raise ValueError("freeze requires --update-baseline to write baseline outputs")

    cfg = settings or get_settings()
    summary = run_multi_turn_eval_suite(
        scenarios,
        settings=cfg,
        provider="openai",
        enable_knowledge_hints=enable_knowledge_hints,
        scenarios_path=scenarios_path,
    )
    scenarios_by_id = {item.scenario_id: item for item in scenarios}
    real_failures, critical_count, high_count = _triage_counts(
        summary.results,
        scenarios_by_id,
    )

    reflection_metrics = reflection_metrics_from_results(summary.results)
    manifest = build_manifest_from_run(
        summary,
        settings=cfg,
        reflection_metrics=reflection_metrics,
    )

    written = 0
    for result in summary.results:
        record = scenario_record_from_eval_result(result)
        write_baseline_scenario_record(
            record,
            baseline_dir=baseline_dir,
            overwrite=True,
        )
        written += 1
    write_baseline_manifest(manifest, baseline_dir=baseline_dir, overwrite=True)

    freeze_ok = (
        summary.failed_count == 0 and real_failures == 0 and critical_count == 0 and high_count == 0
    )
    status = "passed" if freeze_ok else "failed"
    return BaselineFreezeSummary(
        status=status,
        baseline_dir=str(baseline_dir),
        update_baseline=update_baseline,
        eval_summary=summary,
        manifest=manifest,
        triage_real_failures=real_failures,
        triage_critical_count=critical_count,
        triage_high_count=high_count,
        scenario_files_written=written,
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def compare_openai_baseline(
    *,
    scenarios: Sequence[EvalScenario],
    settings: AppSettings | None = None,
    enable_knowledge_hints: bool = True,
    baseline_dir: Path = DEFAULT_OPENAI_BASELINE_DIR,
    scenarios_path: Path = DEFAULT_SCENARIOS_PATH,
    provider: str = "openai",
) -> BaselineCompareSummary:
    """Run current suite and compare against frozen OpenAI baseline."""
    if provider.strip().lower() != "openai":
        raise ValueError("baseline compare requires provider=openai")

    cfg = settings or get_settings()
    summary = run_multi_turn_eval_suite(
        scenarios,
        settings=cfg,
        provider="openai",
        enable_knowledge_hints=enable_knowledge_hints,
        scenarios_path=scenarios_path,
    )
    current_records: dict[str, BaselineScenarioRecord] = {}
    for result in summary.results:
        current_records[result.scenario_id] = scenario_record_from_eval_result(result)
    baseline_records = load_all_baseline_records(baseline_dir=baseline_dir)
    manifest = load_baseline_manifest(baseline_dir=baseline_dir)
    scenarios_by_id = {item.scenario_id: item for item in scenarios}
    return compare_baseline_records(
        baseline_records,
        current_records,
        scenarios_by_id=scenarios_by_id,
        manifest=manifest,
        baseline_dir=baseline_dir,
    )


def render_freeze_report_markdown(summary: BaselineFreezeSummary) -> str:
    """Human-readable freeze report."""
    lines = [
        "# OpenAI multi-turn baseline freeze report",
        "",
        f"**Status:** {summary.status}",
        f"**Generated:** {summary.generated_at_utc}",
        f"**Baseline directory:** `{summary.baseline_dir}`",
        "",
        "## Eval suite",
        "",
        f"- pass_rate: {summary.eval_summary.pass_rate:.1%} "
        f"({summary.eval_summary.passed_count}/{summary.eval_summary.total_scenarios})",
        f"- reflection_rewrite_count: {summary.eval_summary.reflection_rewrite_count}",
        f"- reflection_saved_bad_draft_count: "
        f"{summary.eval_summary.reflection_saved_bad_draft_count}",
        "",
        "## Triage gate",
        "",
        f"- real_failures: {summary.triage_real_failures}",
        f"- critical: {summary.triage_critical_count}",
        f"- high: {summary.triage_high_count}",
        "",
        "## Frozen manifest",
        "",
        f"- model: {summary.manifest.model or '—'}",
        f"- knowledge_hints_enabled: {summary.manifest.knowledge_hints_enabled}",
        f"- multi_turn_context_enabled: {summary.manifest.multi_turn_context_enabled}",
        f"- reflection_provider: {summary.manifest.reflection_provider or '—'}",
        f"- rewrite_rate: {summary.manifest.reflection_metrics.rewrite_rate:.1%}",
        f"- reflection_save_rate: {summary.manifest.reflection_metrics.save_rate:.1%}",
        "",
        f"Scenarios written: {summary.scenario_files_written}",
        "",
    ]
    text = "\n".join(lines)
    assert_report_safe(text)
    return text


def render_compare_report_markdown(summary: BaselineCompareSummary) -> str:
    """Human-readable baseline comparison report."""
    lines = [
        "# OpenAI multi-turn baseline comparison report",
        "",
        f"**Status:** {summary.status}",
        f"**Generated:** {summary.generated_at_utc}",
        f"**Baseline directory:** `{summary.baseline_dir}`",
        "",
        "## Drift summary",
        "",
        f"- unchanged: {summary.unchanged_count}",
        f"- acceptable: {summary.acceptable_drift_count}",
        f"- review_required: {summary.review_required_count}",
        f"- critical_regression: {summary.critical_regression_count}",
        "",
    ]
    if summary.reflection_metrics_delta:
        lines.append("## Reflection metrics delta")
        lines.append("")
        for key, value in summary.reflection_metrics_delta.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    drift_items = [item for item in summary.items if item.drift_class != BaselineDriftClass.NONE]
    lines.append(f"## Drift details ({len(drift_items)})")
    lines.append("")
    if not drift_items:
        lines.append("_No drift detected vs frozen baseline._")
        lines.append("")
    for item in drift_items:
        lines.append(f"### {item.scenario_id}")
        lines.append("")
        lines.append(f"- **class:** {item.drift_class.value}")
        lines.append(f"- **reasons:** {', '.join(item.reasons) or '—'}")
        if item.baseline is not None:
            lines.append(
                f"- **baseline:** intent={item.baseline.detected_intent or '—'} "
                f"action={item.baseline.suggested_action or '—'} "
                f"rewrite={item.baseline.reflection_rewrite_applied}",
            )
        if item.current is not None:
            lines.append(
                f"- **current:** intent={item.current.detected_intent or '—'} "
                f"action={item.current.suggested_action or '—'} "
                f"rewrite={item.current.reflection_rewrite_applied}",
            )
        lines.append("")

    text = "\n".join(lines)
    assert_report_safe(text)
    return text


def write_baseline_reports(
    *,
    freeze_summary: BaselineFreezeSummary | None = None,
    compare_summary: BaselineCompareSummary | None = None,
    freeze_summary_json: Path = DEFAULT_FREEZE_SUMMARY_JSON,
    freeze_report_md: Path = DEFAULT_FREEZE_REPORT_MD,
    compare_summary_json: Path = DEFAULT_COMPARE_SUMMARY_JSON,
    compare_report_md: Path = DEFAULT_COMPARE_REPORT_MD,
    overwrite: bool = False,
) -> None:
    """Write freeze and/or compare report artifacts."""
    if freeze_summary is not None:
        if freeze_summary_json.exists() and not overwrite:
            raise FileExistsError(f"exists: {freeze_summary_json}")
        freeze_summary_json.write_text(
            json.dumps(freeze_summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        md = render_freeze_report_markdown(freeze_summary)
        if freeze_report_md.exists() and not overwrite:
            raise FileExistsError(f"exists: {freeze_report_md}")
        freeze_report_md.write_text(md, encoding="utf-8")

    if compare_summary is not None:
        if compare_summary_json.exists() and not overwrite:
            raise FileExistsError(f"exists: {compare_summary_json}")
        compare_summary_json.write_text(
            json.dumps(compare_summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        md = render_compare_report_markdown(compare_summary)
        if compare_report_md.exists() and not overwrite:
            raise FileExistsError(f"exists: {compare_report_md}")
        compare_report_md.write_text(md, encoding="utf-8")
